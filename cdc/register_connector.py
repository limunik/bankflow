import json
import os
import sys
import time
import urllib.error
import urllib.request

CONNECT_URL = os.environ.get("CONNECT_URL", "http://connect:8083")
NAME = "bankflow-oltp-accounts"


def config():
    return {
        "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
        "plugin.name": "pgoutput",
        "database.hostname": os.environ["OLTP_HOST"],
        "database.port": os.environ.get("OLTP_PORT", "5432"),
        "database.user": os.environ["OLTP_USER"],
        "database.password": os.environ["OLTP_PASSWORD"],
        "database.dbname": os.environ["OLTP_DB"],
        "topic.prefix": "bankflow",
        "table.include.list": "bank.accounts",
        "slot.name": "bankflow_slot",
        "publication.name": "bankflow_pub",
        "publication.autocreate.mode": "filtered",
        "snapshot.mode": "initial",
        "decimal.handling.mode": "string",
        "tombstones.on.delete": "false",
        "key.converter": "org.apache.kafka.connect.json.JsonConverter",
        "key.converter.schemas.enable": "false",
        "value.converter": "org.apache.kafka.connect.json.JsonConverter",
        "value.converter.schemas.enable": "false",
        "topic.creation.default.replication.factor": "3",
        "topic.creation.default.partitions": "3",
    }


def request(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(CONNECT_URL + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.status, response.read().decode()


def main():
    for _ in range(60):
        try:
            request("GET", "/connectors")
            break
        except (urllib.error.URLError, ConnectionError):
            time.sleep(3)
    else:
        sys.exit("Kafka Connect не отвечает")
    status, body = request("PUT", f"/connectors/{NAME}/config", config())
    print(status)
    time.sleep(5)
    print(request("GET", f"/connectors/{NAME}/status")[1])


if __name__ == "__main__":
    main()
