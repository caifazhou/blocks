import os
import shutil
import tempfile
from collections import defaultdict
from pickle import HIGHEST_PROTOCOL
try:
    from pickle import DEFAULT_PROTOCOL
except ImportError:
    DEFAULT_PROTOCOL = HIGHEST_PROTOCOL

import theano
from theano.compile.sharedvalue import SharedVariable
from theano.misc import pkl_utils
from theano.misc.pkl_utils import PersistentNdarrayID

from blocks.config import config
from blocks.utils import change_recursion_limit


BRICK_DELIMITER = '/'


class PersistentParameterID(PersistentNdarrayID):
    """Persist the names of parameter arrays in the zip file.

    If a shared variable has a name, this name is used as the name of the
    NPY file inside of the zip file. NumPy arrays that aren't matched to a
    shared variable are persisted as usual (i.e. `array_0`, `array_1`,
    etc.)

    Parameters
    ----------
    allow_unnamed : bool, optional
        Allow shared variables without a name to be persisted. Defaults to
        ``True``.
    allow_duplicates : bool, optional
        Allow multiple shared variables to have the same name, in which
        case they will be numbered e.g. `x`, `x_2`, `x_3`, etc. Defaults to
        ``True``.

    Raises
    ------
    ValueError
        If an unnamed shared variable is encountered and `allow_unnamed` is
        ``False``, or if two shared variables have the same name, and
        `allow_duplicates` is ``False``.

    """
    def __init__(self, zip_file, allow_unnamed=True, allow_duplicates=True):
        super(PersistentParameterID, self).__init__(zip_file)
        self.name_counter = defaultdict(int)
        self.ndarray_names = {}
        self.allow_unnamed = allow_unnamed
        self.allow_duplicates = allow_duplicates

    def _resolve_name(self, obj):
        if id(obj) in self.ndarray_names:
            name = self.ndarray_names[id(obj)]
            count = self.name_counter[name]
            if count:
                if not self.allow_duplicates:
                    raise ValueError("multiple shared variables with the name "
                                     "`{0}` found".format(name))
                name = '{0}_{1}'.format(name, count + 1)
            self.name_counter[name] += 1
            return name
        return super(PersistentParameterID, self)._resolve_name(obj)

    def __call__(self, obj):
        if isinstance(obj, SharedVariable):
            if obj.name:
                if obj.name == 'pkl':
                    ValueError("can't pickle shared variable with name `pkl`")
                if hasattr(obj.tag, 'annotations'):
                    name = BRICK_DELIMITER.join(
                        [brick.name for brick
                         in obj.tag.annotations[0].get_unique_path()] +
                        [obj.name])
                else:
                    name = obj.name
                self.ndarray_names[id(obj.container.storage[0])] = name
            elif not self.allow_unnamed:
                raise ValueError("unnamed shared variable, {}".format(obj))
        return super(PersistentParameterID, self).__call__(obj)


def dump(obj, f, protocol=DEFAULT_PROTOCOL,
         persistent_id=PersistentParameterID):
    """Pickles an object to a zip file using external persistence.

    Parameters
    ----------
    obj : object
        The object to pickle.
    f : file
        The file handle to save the object to.
    protocol : int, optional
        The pickling protocol to use. Unlike Python's built-in pickle, the
        default is set to `2` insstead of 0 for Python 2. The Python 3
        default (level 3) is maintained.
    persistent_id : callable
        The callable that persists certain objects in the object hierarchy
        to separate files inside of the zip file. For example,
        :class:`PersistentNdarrayID` saves any :class:`numpy.ndarray` to a
        separate NPY file inside of the zip file.

    Notes
    -----
    The final file is simply a zipped file containing at least one file,
    `pkl`, which contains the pickled object. It can contain any other
    number of external objects. Note that the zip files are compatible with
    NumPy's :func:`numpy.load` function.

    >>> import numpy
    >>> from theano.misc.pkl_utils import load
    >>> from blocks.bricks import MLP, Identity
    >>> from blocks.initialization import Constant
    >>> mlp = MLP([Identity()], [10, 10], weights_init=Constant(0.),
    ...           biases_init=Constant(0.))
    >>> mlp.initialize()
    >>> with open('model.zip', 'wb') as f:
    ...     dump(mlp, f)
    >>> 'mlp/linear_0/W' in numpy.load('model.zip').keys()
    True
    >>> 'mlp/linear_0/b' in numpy.load('model.zip').keys()
    True
    >>> numpy.load('model.zip')['mlp/linear_0/W'].shape
    (10, 10)
    >>> with open('model.zip', 'rb') as f:
    ...     mlp2 = load(f)
    >>> mlp2  # doctest: +ELLIPSIS
    <blocks.bricks.MLP object at ...: name=mlp>

    """
    theano.misc.pkl_utils.dump(obj, f, protocol, persistent_id)


# A thin wrapper around Theano load.
load = pkl_utils.load


def secure_pickle_dump(object_, path):
    """Robust serialization - does not corrupt your files when failed.

    Parameters
    ----------
    object_ : object
        The object to be saved to the disk.
    path : str
        The destination path.

    """
    try:
        with tempfile.NamedTemporaryFile(delete=False) as temp:
            dump(object_, temp)
        shutil.move(temp.name, path)
    except:
        if "temp" in locals():
            os.remove(temp.name)
        raise


def continue_training(path):
    """Continues training using checkpoint.

    Parameters
    ----------
    path : str
        Path to checkpoint.

    Notes
    -----
    Python picklers can unpickle objects from global namespace only if
    they are present in namespace where unpickling happens. Often global
    functions are needed for mapping, filtering and other data stream
    operations. In a case if the main loop uses global objects and
    this function fails with a message like
    ```
    AttributeError: 'module' object has no attribute '...'
    ```
    it means that you need to import these objects.

    Examples
    --------
    This function can be used in two ways: in your script where a main
    loop defined or in a different script. For later options see Notes
    section.

    """
    with change_recursion_limit(config.recursion_limit):
        with open(path, "rb") as f:
            main_loop = load(f)
    main_loop.run()
