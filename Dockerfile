# Same base image the track labeled commits in (its Python decides which sqlglot tests run).
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
COPY fetch_sqlglot.py /tmp/
# sqlglot source at the pinned commit; the selector imports a patched copy to see if a patch breaks import.
# If this step fails the image still builds and the selector falls back to the conservative path.
RUN (python /tmp/fetch_sqlglot.py /opt/sg && python -m compileall -q /opt/sg/sqlglot) || echo "sqlglot fetch skipped"
COPY selector.py map.json /app/
CMD ["python", "/app/selector.py"]
