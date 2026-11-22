"""Build step: put sqlglot's package source at the pinned commit in /opt/sg (used by the selector's import check)."""
import io, sys, tarfile, urllib.request
SHA = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
dest = sys.argv[1] if len(sys.argv) > 1 else "/opt/sg"
data = urllib.request.urlopen(f"https://codeload.github.com/tobymao/sqlglot/tar.gz/{SHA}", timeout=120).read()
with tarfile.open(fileobj=io.BytesIO(data)) as t:
    top = t.getnames()[0].split("/")[0]
    members = [m for m in t.getmembers() if m.name.startswith(f"{top}/sqlglot/")]
    for m in members:
        m.name = m.name[len(top) + 1:]
    t.extractall(dest, members=members)
