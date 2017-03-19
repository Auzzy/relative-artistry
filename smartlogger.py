import logging
import operator
import sys

class ThreshholdFilter(logging.Filter):
    def __init__(self, level, comparator):
        self.level = level
        self._comparator = comparator

    def filter(self, record):
        return self._comparator(record.levelno, self.level)

class MinimumLevelFilter(ThreshholdFilter):
    def __init__(self, level, inclusive=True):
        comparator = operator.ge if inclusive else operator.gt
        super(MinimumLevelFilter, self).__init__(level, comparator)

class MaximumLevelFilter(ThreshholdFilter):
    def __init__(self, level, inclusive=True):
        comparator = operator.le if inclusive else operator.lt
        super(MaximumLevelFilter, self).__init__(level, comparator)

def create_logger(level, name=__file__, stderr_threshhold=logging.WARN):
    formatter = logging.Formatter()

    stdout_filter = MaximumLevelFilter(logging.WARN, inclusive=False)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.addFilter(stdout_filter)
    stdout_handler.setFormatter(formatter)

    stderr_filter = MinimumLevelFilter(logging.WARN, inclusive=True)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.addFilter(stderr_filter)
    stderr_handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(stdout_handler)
    logger.addHandler(stderr_handler)
    return logger