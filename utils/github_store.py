"""
utils/github_store.py — Scrittura affidabile dei CSV sul repository GitHub.

Perché esiste
-------------
Il vecchio flusso "Add Transaction" costruiva il CSV a partire dal DataFrame
in memoria, che arriva da load_funds_and_transactions() con cache di 5 minuti.
Dopo il primo inserimento il rerun rileggeva la CACHE (senza la riga appena
aggiunta), quindi il secondo inserimento pushava "vecchio CSV + riga 2" e
sovrascriveva la riga 1 su GitHub. Risultato: di 6 inserimenti consecutivi ne
sopravvivevano 1-2.

Come funziona ora
-----------------
GitHub è l'unica fonte di verità. Ogni scrittura è un read-modify-write:
    1. GET del file dal repo (contenuto + sha), senza cache;
    2. si APPENDONO le nuove righe al testo remoto (le righe esistenti restano
       identiche byte per byte: nessuna riformattazione di float o date);
    3. PUT con lo sha letto: se nel frattempo qualcun altro ha scritto il file
       GitHub risponde 409 e si riparte dal punto 1 (concorrenza ottimistica);
    4. dopo il PUT si rilegge il file e si verifica che contenga esattamente
       quanto scritto.
Errori transitori (timeout, 5xx, rate limit) vengono ritentati con backoff.
Prima di ogni nuovo tentativo si controlla se il PUT precedente era in
realtà andato a buon fine (es. timeout lato client dopo il commit), così una
riga non viene mai scritta due volte.

Modulo puro: nessuna dipendenza da Streamlit, testabile in isolamento.
"""

from __future__ import annotations

import base64
import io
import threading
import time
from dataclasses import dataclass

import pandas as pd
import requests

API = "https://api.github.com"

# Serializza le scritture dallo stesso processo (es. due tab aperte).
_WRITE_LOCK = threading.Lock()


class GitHubWriteError(RuntimeError):
    """Scrittura non riuscita: i dati NON sono su GitHub."""


class GitHubConfigError(GitHubWriteError):
    """Token/permessi/repo errati: inutile ritentare."""


@dataclass
class CommitResult:
    content: str          # testo completo del file come ora è su GitHub
    commit_sha: str | None
    commit_url: str | None
    attempts: int
    already_present: bool = False   # un tentativo precedente era già andato a buon fine


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        # Evita letture stale dalla cache CDN dopo un commit appena fatto
        "Cache-Control": "no-cache",
    }


def get_file(repo: str, path: str, branch: str, token: str,
             timeout: int = 20) -> tuple[str | None, str | None]:
    """Restituisce (contenuto, sha) del file sul branch; (None, None) se non esiste."""
    r = requests.get(f"{API}/repos/{repo}/contents/{path}",
                     params={"ref": branch}, headers=_headers(token), timeout=timeout)
    if r.status_code == 404:
        return None, None
    if r.status_code in (401, 403) and "rate limit" not in r.text.lower():
        raise GitHubConfigError(f"GitHub {r.status_code}: check GITHUB_TOKEN permissions "
                                f"(needs Contents: read & write on {repo})")
    r.raise_for_status()
    j = r.json()
    if j.get("encoding") == "base64" and j.get("content") is not None:
        text = base64.b64decode(j["content"]).decode("utf-8")
    else:
        # File > 1 MB: il contents API non include il contenuto, usa il blob raw
        raw = requests.get(f"{API}/repos/{repo}/contents/{path}", params={"ref": branch},
                           headers={**_headers(token), "Accept": "application/vnd.github.raw+json"},
                           timeout=timeout)
        raw.raise_for_status()
        text = raw.text
    return text, j.get("sha")


def rows_to_csv_lines(rows: pd.DataFrame, columns: list[str]) -> str:
    """Righe CSV (senza header) nello stesso formato di DataFrame.to_csv."""
    buf = io.StringIO()
    rows[columns].to_csv(buf, index=False, header=False, lineterminator="\n")
    return buf.getvalue()


def _append(base_text: str | None, header_line: str, new_lines: str) -> str:
    if not base_text or not base_text.strip():
        return header_line + "\n" + new_lines
    return (base_text if base_text.endswith("\n") else base_text + "\n") + new_lines


def _check_header(base_text: str | None, columns: list[str]) -> None:
    if not base_text or not base_text.strip():
        return
    remote_cols = list(pd.read_csv(io.StringIO(base_text), nrows=0).columns)
    if remote_cols != columns:
        raise GitHubConfigError(
            f"Columns on GitHub {remote_cols} differ from the app's {columns}: "
            "refusing to write to avoid corrupting the file.")


def append_csv_rows(repo: str, path: str, branch: str, token: str,
                    rows: pd.DataFrame, columns: list[str], message: str,
                    max_attempts: int = 6, sleep=time.sleep) -> CommitResult:
    """Appende `rows` al CSV `path` sul repo, con retry e verifica.

    Raises:
        GitHubConfigError: token/permessi/header errati (nessun retry).
        GitHubWriteError:  tentativi esauriti; le righe NON sono su GitHub.
    """
    if not token or not repo:
        raise GitHubConfigError("GITHUB_TOKEN / GITHUB_REPO not configured")
    if rows is None or len(rows) == 0:
        raise ValueError("No rows to append")

    header_line = ",".join(columns)
    new_lines = rows_to_csv_lines(rows, columns)
    last_intended: str | None = None
    last_err = "unknown error"

    with _WRITE_LOCK:
        for attempt in range(1, max_attempts + 1):
            try:
                base_text, sha = get_file(repo, path, branch, token)

                # Un PUT precedente (fallito lato client) era in realtà riuscito?
                if last_intended is not None and base_text == last_intended:
                    return CommitResult(base_text, None, None, attempt, already_present=True)

                _check_header(base_text, columns)
                intended = _append(base_text, header_line, new_lines)
                last_intended = intended

                body = {
                    "message": message,
                    "content": base64.b64encode(intended.encode("utf-8")).decode("ascii"),
                    "branch": branch,
                }
                if sha:
                    body["sha"] = sha
                r = requests.put(f"{API}/repos/{repo}/contents/{path}",
                                 headers=_headers(token), json=body, timeout=30)

                if r.status_code in (200, 201):
                    commit = (r.json() or {}).get("commit") or {}
                    # Verifica read-after-write (tollera qualche secondo di latenza)
                    for wait in (0, 1, 2, 4):
                        if wait:
                            sleep(wait)
                        check_text, _ = get_file(repo, path, branch, token)
                        if check_text == intended:
                            return CommitResult(intended, commit.get("sha"),
                                                commit.get("html_url"), attempt)
                    # Il commit c'è (200) ma la lettura non lo conferma: riparti
                    # dal GET, che riconoscerà il contenuto se è arrivato.
                    last_err = "commit not visible on read-back"
                    continue

                if r.status_code in (409, 422):
                    # sha superato: il file è cambiato nel frattempo -> rileggi
                    last_err = f"conflict ({r.status_code})"
                    sleep(0.5 * attempt)
                    continue
                if r.status_code in (401, 404) or (
                        r.status_code == 403 and "rate limit" not in r.text.lower()):
                    raise GitHubConfigError(
                        f"GitHub {r.status_code}: check GITHUB_TOKEN permissions "
                        f"(needs Contents: read & write on {repo})")
                last_err = f"HTTP {r.status_code}"
            except GitHubConfigError:
                raise
            except (requests.RequestException, ValueError) as e:
                last_err = f"{type(e).__name__}: {e}"
            sleep(min(2 ** attempt, 20))

    raise GitHubWriteError(f"Push failed after {max_attempts} attempts ({last_err})")
