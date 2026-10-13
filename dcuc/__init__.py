"""dcuc - a production-style sample application built on docling-context.

The package is split into small, individually testable modules:

* :mod:`dcuc.config`      - typed settings loaded from the environment / ``.env``
* :mod:`dcuc.logging_setup` - one place to configure logging
* :mod:`dcuc.uris`        - safe mapping of input files to ``docling://`` URIs
* :mod:`dcuc.converters`  - lightweight Markdown/text -> DocLang converter
* :mod:`dcuc.llm`         - minimal OpenAI-compatible client for a *local* LLM
* :mod:`dcuc.summaries`   - LLM-backed ``SummaryProvider`` for ingestion
* :mod:`dcuc.pipeline`    - the ``ContextPipeline`` facade (ingest / search / chat)
* :mod:`dcuc.reporting`   - timestamped reports written to ``output/``
* :mod:`dcuc.cli`         - command line entry point (``dcuc``)
"""

__version__ = "0.1.0"
