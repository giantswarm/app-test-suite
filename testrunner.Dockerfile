FROM quay.io/giantswarm/app-test-suite:latest

ARG ATS_DIR="/ats"

RUN pip install --no-cache-dir pipenv==${PIPENV_VER}
RUN apt-get update && apt-get install -y wget xz-utils && rm -rf /var/lib/apt/lists/*
RUN wget -qO- "https://github.com/koalaman/shellcheck/releases/download/latest/shellcheck-latest.linux.x86_64.tar.xz" | tar -xJv && cp "shellcheck-latest/shellcheck" /usr/bin/
WORKDIR $ATS_DIR
COPY .bandit .
COPY .coveragerc .
COPY .flake8 .
COPY .mypy.ini .
COPY .pre-commit-config.yaml .
COPY pyproject.toml .
COPY run-tests-in-docker.sh .
COPY Pipfile .
COPY Pipfile.lock .
COPY tests/ tests/
COPY examples/ examples/
COPY .git/ ./.git/
RUN PIPENV_VENV_IN_PROJECT=1 pipenv install --deploy --clear --dev
RUN pipenv run pre-commit install-hooks
ENTRYPOINT ["./run-tests-in-docker.sh"]
CMD ["--cov", "app_test_suite", "--log-cli-level", "info", "tests/"]
