FROM python:3.12-slim
RUN pip install --no-cache-dir "dbt-core==1.9.4" "dbt-postgres==1.9.0"
WORKDIR /dbt
COPY . /dbt
ENV DBT_PROFILES_DIR=/dbt
