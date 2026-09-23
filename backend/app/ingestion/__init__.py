"""Repository ingestion: validate a source, clone it safely, analyse it, index its files.

Security model — CodeSage *reads* repositories, it never *runs* them:

* Sources are validated before use (`sources.py`): only public GitHub HTTPS URLs,
  or local paths inside configured roots in development.
* Git runs as a subprocess with an argument list (never a shell), a sanitised
  environment and hardened configuration (`git.py`): no hooks, no credential
  prompts, no symlinks in checkouts, only the expected transport protocol.
* Checkouts live under a single storage root; every path is derived from the
  repository's UUID and verified to stay inside that root (`storage.py`).
* Analysis only reads bytes from files (`scanner.py`); no repository file is
  imported, executed, or passed to a build tool.
"""
