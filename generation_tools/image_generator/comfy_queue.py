"""
Queue-based serialization for ComfyLocal image generation.
All ComfyUI requests flow through a single consumer process to enforce one-at-a-time execution.
"""

import uuid
from pathlib import Path
import multiprocessing
from multiprocessing import Process, Manager, current_process
from typing import Union

from loguru import logger
from generation_tools.image_generator.comfy_local import ComfyLocal


def spawn_image_consumer():
    """
    Initialize a Manager queue and start the single consumer process.
    Returns:
      task_queue: multiprocessing.Manager.Queue
      consumer: multiprocessing.Process
    """
    manager = Manager()
    task_queue = manager.Queue()
    consumer = Process(
        target=_image_consumer_worker,
        args=(task_queue,),
        name="ImageConsumer",
        daemon=True,
    )
    consumer.start()
    return task_queue, consumer


def _image_consumer_worker(task_queue: multiprocessing.Queue):
    """
    Consumer loop: pull tasks and call ComfyLocal.generate_image serially.
    """
    logger.info("[ImageConsumer] Started")
    clients: dict[str, ComfyLocal] = {}
    while True:
        task = task_queue.get()
        if task is None:
            logger.info("[ImageConsumer] Shutting down")
            break

        workflow_path_str, prompt, output_path_str, width, height, seed = task
        workflow_path = Path(workflow_path_str)
        output_path = Path(output_path_str)

        # reuse a ComfyLocal instance per workflow file
        client = clients.get(workflow_path_str)
        if client is None:
            client = ComfyLocal(workflow_path=workflow_path)
            clients[workflow_path_str] = client

        try:
            client.generate_image(prompt, output_path, width, height, seed)
            logger.info(f"[ImageConsumer] Generated -> {output_path}")
        except Exception as e:
            logger.error(f"[ImageConsumer] Error generating '{prompt[:30]}...': {e}")
    logger.info("[ImageConsumer] Exited")


class QueueComfyClient:
    """
    Stub client implementing ComfyLocal interface:
    enqueues generation tasks instead of executing immediately.
    """

    def __init__(self, task_queue: multiprocessing.Queue, workflow_path: Path):
        self.task_queue = task_queue
        self.workflow_path = workflow_path

    def generate_image(
        self,
        prompt: str,
        output_path: Path,
        width: int = 512,
        height: int = 768,
        seed: Union[int, None] = None,
    ) -> bool:
        seed = seed or (uuid.uuid4().int & ((1 << 32) - 1))
        self.task_queue.put(
            (
                str(self.workflow_path),
                prompt,
                str(output_path),
                width,
                height,
                seed,
            )
        )
        logger.debug(
            f"[QueueClient:{current_process().name}] Enqueued '{prompt[:30]}...' -> {output_path}"
        )
        return True
