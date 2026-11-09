import logging
import os
import signal
import sys
import time

import psycopg2
from confluent_kafka import Consumer, KafkaError, KafkaException

import cdc_lib

LOG = logging.getLogger("cdc_consumer")
BATCH_SIZE = int(os.environ.get("CDC_BATCH_SIZE", "500"))
BATCH_WAIT = float(os.environ.get("CDC_BATCH_WAIT", "0.5"))
RUNNING = True


def stop(*_):
    global RUNNING
    RUNNING = False


def connect():
    return psycopg2.connect(
        host=os.environ["DWH_HOST"],
        port=os.environ.get("DWH_PORT", "5432"),
        dbname=os.environ["DWH_DB"],
        user=os.environ["DWH_USER"],
        password=os.environ["DWH_PASSWORD"],
    )


def build_consumer():
    return Consumer({
        "bootstrap.servers": os.environ.get("KAFKA_BOOTSTRAP", "kafka1:9092,kafka2:9092,kafka3:9092"),
        "group.id": os.environ.get("CDC_GROUP", "bankflow-ods-accounts"),
        "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
        "partition.assignment.strategy": "cooperative-sticky",
    })


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    consumer = build_consumer()
    consumer.subscribe([cdc_lib.TOPIC])
    connection = None
    while connection is None and RUNNING:
        try:
            connection = connect()
        except psycopg2.OperationalError as error:
            LOG.warning("dwh недоступен: %s", error)
            time.sleep(3)
    LOG.info("потребитель запущен, топик %s", cdc_lib.TOPIC)
    while RUNNING:
        messages = consumer.consume(num_messages=BATCH_SIZE, timeout=BATCH_WAIT)
        events = []
        for message in messages:
            if message.error():
                code = message.error().code()
                if code in (KafkaError._PARTITION_EOF, KafkaError.UNKNOWN_TOPIC_OR_PART):
                    LOG.info("топика пока нет или конец партиции: %s", message.error())
                    time.sleep(2)
                    continue
                raise KafkaException(message.error())
            event = cdc_lib.parse_message(message.key(), message.value(), message.topic(),
                                          message.partition(), message.offset())
            if event:
                events.append(event)
        if not events:
            continue
        result = cdc_lib.process_batch(connection, events)
        consumer.commit(asynchronous=False)
        LOG.info("сообщений %s, применено событий %s, счетов изменено %s, мягких удалений %s",
                 len(messages), result["applied"], result["accounts"], result["deleted"])
    consumer.close()
    connection.close()


if __name__ == "__main__":
    sys.exit(main())
