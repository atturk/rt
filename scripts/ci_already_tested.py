"""Dice a release.yml se il codice da pubblicare ha già i test verdi, per non rifarli.

Candidati: il commit stesso (release di una beta dalla testa del branch) e, se è un merge con
lo stesso albero della testa della PR (main era già dentro il branch), quella testa. Serve un
giro "Test Suite" con tutti i job verdi (nessuno saltato: un giro 'labeled' salta tutto) e un
giro "App" con la suite su Windows verde. Scrive tested=true|false per $GITHUB_OUTPUT.

Uso: GH_TOKEN=... python scripts/ci_already_tested.py owner/repo
"""
import json
import os
import subprocess
import sys
import urllib.request

API = "https://api.github.com"


def git(*args):
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def candidates():
    head = git("rev-parse", "HEAD")
    found = [head]
    second = git("rev-parse", "-q", "--verify", "HEAD^2")
    if second and git("rev-parse", "HEAD^{tree}") == git("rev-parse", "HEAD^2^{tree}"):
        found.append(second)
    return found


def get(path):
    request = urllib.request.Request(f"{API}/{path}", headers={
        "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
        "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def green(repo, workflow, sha, required):
    """Un giro riuscito di workflow su sha in cui ogni job richiesto è verde (non saltato)."""
    runs = get(f"repos/{repo}/actions/workflows/{workflow}/runs?head_sha={sha}&status=success")
    for run in runs.get("workflow_runs", []):
        jobs = get(f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100").get("jobs", [])
        if required(jobs):
            return run["html_url"]
    return None


def all_jobs_green(jobs):
    return bool(jobs) and any(job["name"].startswith("test (") for job in jobs) \
        and all(job["conclusion"] == "success" for job in jobs)


def windows_suite_green(jobs):
    return any(job["name"] == "test-windows" and job["conclusion"] == "success" for job in jobs)


def main(repo):
    for sha in candidates():
        try:
            tests = green(repo, "tests.yml", sha, all_jobs_green)
            app = tests and green(repo, "app.yml", sha, windows_suite_green)
        except OSError as error:  # API irraggiungibile: meglio rifare i test
            print(f"::warning::Controllo dei test già fatti non riuscito: {error}", file=sys.stderr)
            break
        if tests and app:
            print(f"Test già verdi su {sha}: {tests} e {app}", file=sys.stderr)
            print("tested=true")
            return
    print("Nessun giro verde sullo stesso codice: la release rifà i test", file=sys.stderr)
    print("tested=false")


if __name__ == "__main__":
    main(sys.argv[1])
