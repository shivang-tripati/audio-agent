# worker_main.py

import time
import logging
from utils.single_instance import SingleInstance
from utils.logger import setup_logging

setup_logging("worker")
logger = logging.getLogger(__name__)


def run_worker():

    from main import AudioAgent
    logger.info("Starting AudioAgent Worker")
    instance = SingleInstance()

    while True:
        try:
            agent = AudioAgent()
            agent.start()
        except Exception as e:
            logger.exception("Worker crashed")

        # small delay before restart inside worker loop
        time.sleep(5)
