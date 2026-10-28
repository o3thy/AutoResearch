"""A shell-free adapter for the current BrowserAct CLI."""

import json
import os
import shutil
import subprocess


class BrowserError(RuntimeError):
    pass


class BrowserAct:
    def __init__(self, session="rr-zotero-obsidian", executable="browser-act", timeout=45):
        self.executable = shutil.which(executable)
        if not self.executable:
            raise BrowserError("BrowserAct not found. Install it or use the saved-HTML replay command.")
        self.session = session
        self.timeout = timeout

    def run(self, *arguments, stdin=None):
        command = [self.executable, "--session", self.session, "--format", "json",
                   "--no-auto-dialog", *arguments]
        try:
            process = subprocess.run(command, input=stdin, capture_output=True, text=True,
                                     encoding="utf-8", errors="replace", timeout=self.timeout,
                                     shell=False, env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
        except subprocess.TimeoutExpired as exc:
            raise BrowserError(f"BrowserAct timed out after {self.timeout}s; inspect the session before retrying.") from exc
        try:
            response = json.loads(process.stdout or process.stderr)
        except json.JSONDecodeError as exc:
            raise BrowserError("BrowserAct returned invalid JSON; check CLI version and connectivity.") from exc
        if process.returncode or response.get("ok") is False:
            raise BrowserError(response.get("error") or "BrowserAct command failed.")
        return response

    def evaluate(self, code):
        response = self.run("eval", "--stdin", stdin=code)
        if "result" not in response:
            raise BrowserError("BrowserAct eval response has no result field.")
        return response["result"]

    def html(self):
        return self.run("get", "html")["html"]

    def click(self, selector):
        self.run("click", "--selector", selector)

    def input(self, selector, value):
        self.run("input", "--selector", selector, "--text", value, "--mode", "fill")

    def snapshot(self):
        # DOM evidence only: do not read cookies, application state, or private network APIs.
        return self.evaluate("""(() => {
          const results = [...document.querySelectorAll('[class*="ListItemContainer-"]')];
          const title = document.querySelector('[class*="ArticleTitle__Title-"]');
          const detail = title?.closest('[class*="InspectorStyles__Content-"]') || title?.parentElement;
          const body = document.body.innerText;
          const range = body.match(/\\b\\d+\\s*[-\\u2013]\\s*\\d+\\s+of\\s+\\d+\\b/);
          const login = !!document.querySelector('input[type="password"]');
          return {url: location.href,
            summary: document.querySelector('[class*="SearchSummary__Container-"]')?.innerText || null,
            query: document.querySelector('input[name="query"]')?.value || null,
            html: results.map(x => x.outerHTML).join('') +
            (detail ? detail.outerHTML : '') + '<p>' + (range ? range[0] : '') + '</p>' +
            (login ? '<input type="password">' : '') +
            (/no (articles|results|papers) (found|available)/i.test(body) ? '<p>No results found</p>' : '') +
            (/verify you are human|complete the captcha|access denied/i.test(body) ? '<p>Verify you are human</p>' : '')};
        })()""")
