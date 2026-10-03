"""The exception raised for every failure this package reports itself."""


class KspSourceAnnotatorError(Exception):
    """A step could not run or did not produce its output.

    The message is complete on its own; the command line prints it and exits
    with status 1.
    """
