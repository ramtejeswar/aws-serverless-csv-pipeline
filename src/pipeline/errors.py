class FileRejected(Exception):
    """The whole file is unusable (too big, not UTF-8, wrong columns, ...).

    This is a permanent failure: retrying the same file gives the same result,
    so the job is marked FAILED instead of sending the message back to the queue.
    """
