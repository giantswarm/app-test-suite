FROM gsoci.azurecr.io/giantswarm/app-test-suite:latest

ARG ATS_DIR="/ats"

RUN apt-get update && apt-get install -y wget xz-utils git libatomic1 && rm -rf /var/lib/apt/lists/*
RUN wget -qO- "https://github.com/koalaman/shellcheck/releases/download/latest/shellcheck-latest.linux.x86_64.tar.xz" | tar -xJv && cp "shellcheck-latest/shellcheck" /usr/bin/
WORKDIR $ATS_DIR
COPY .coveragerc .
COPY .mypy.ini .
COPY .pre-commit-config.yaml .
COPY .markdownlintignore .
COPY .markdownlint.yaml .
COPY pyproject.toml .
COPY run-tests-in-docker.sh .
COPY README.md .
COPY uv.lock .
COPY tests/ tests/
COPY examples/ examples/
COPY .git/ ./.git/
RUN uv sync --frozen --no-install-project --dev
RUN git config --global --add safe.directory /ats
RUN uv tool install pre-commit
RUN pre-commit run -a
ENTRYPOINT ["./run-tests-in-docker.sh"]
CMD ["--cov", "app_test_suite", "--log-cli-level", "info", "tests/"]
