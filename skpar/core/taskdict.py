"""Dictionary with default tasks and their underlying functions."""
import os.path
import subprocess
import matplotlib
import numpy as np
from skpar.core.utils import get_ranges, get_logger
from skpar.core.plot import skparplot
from skpar.core.parameter import update_parameters
matplotlib.use("Agg")

LOGGER = get_logger(__name__)

def execute(implargs, database, cmd, cdir='.', outfile='out.log'):
    """Wrapper over external executables.

    Args:
        implargs(dict): implicit argument passed by the caller
        cmd(list): command to be executed [0] and command line arguments [1:]
        cdir(str): directory, relative to implargs[workroot], where executable
            should be run; if workroot is not found, cdir is relative to '.'
        outfile: output log file

    Raises:
        subprocess.CalledProcessError: if command fails during its execution
        OSError: if command cannot be executed for some reason
    """
    logger = implargs.get('logger', LOGGER)
    #
    def write_out(out, outfile):
        """Write subprocess output to a file"""
        if outfile is not None:
            with open(outfile, 'w') as filep:
                filep.write(out)
            logger.debug("Output is in %s.\n", outfile)
    #
    origdir = os.getcwd()
    workroot = implargs.get('workroot', '.')
    workdir = os.path.normpath(os.path.join(workroot, cdir))
    try:
        os.chdir(workdir)
    except:
        # this should not happen; typically, the workdir should already
        # be there and contain some input file and data
        logger.critical("Cannot change to working directory %s", workdir)
        raise
    #
    if outfile is not None:
        outfile = os.path.normpath(os.path.join(workdir, outfile))
    #
    try:
        logger.debug("Running %s in %s...", cmd, workdir)
        out = subprocess.check_output(
            cmd, universal_newlines=True, stderr=subprocess.STDOUT)
        logger.debug('Done.')
        write_out(out, outfile)
    #
    except subprocess.CalledProcessError as exc:
        logger.critical('The following task failed with exit status %s:\n',
                        exc.returncode)
        write_out(exc.output, outfile)
        raise
    #
    except OSError as exc:
        logger.critical("Abnormal termination: OS could not execute %s in %s",
                        cmd, cdir)
        logger.critical("If the command is a script,"\
                        " make sure there is a shebang!")
        raise
    #
    finally:
        # make sure we return to where we started from in any case!
        os.chdir(origdir)


def get_model_data (implargs, database, src, dst, datakey,
                    rm_columns=None, rm_rows=None, scale=1., **kwargs):
    """Get data from file and put it in a database under a given key.

    Use numpy.loadtxt to get the data from `src` file and write the data
    to `database` under `dst`.`key` field. If `dst` does not exist, it is
    created. All `kwargs` are directly passed to numpy.loadtxt. Additionally,
    some post-processing can be done (removing rows or columns and scaling).

    Args:
        implargs(dict): dictionary of implicit arguments from caller
        database(object): must support dictionary-like insert/get/update()
        src(str): file name (path is relative to `implargs['workroot']`)
        dst(str): name of destination field in `database`
        key(str): key under which to store the data in under `dst`
        rm_columns: [ index, index, [ilow, ihigh], otherindex, [otherrange]]
        rm_rows   : [ index, index, [ilow, ihigh], otherindex, [otherrange]]
        scale(float): multiplier of the data
    """
    logger = implargs.get('logger', LOGGER)
    workroot = implargs.get('workroot', '.')
    assert isinstance(src, str), \
        "src must be a filename string, but is {} instead.".format(type(src))
    assert isinstance(datakey, str),\
        "datakey must be a string naming the data, but is {} instead."\
            .format(type(datakey))
    # read file
    fname = os.path.normpath(os.path.join(workroot, src))
    try:
        data = np.loadtxt(fname, **kwargs)
    except ValueError:
        logger.critical('np.loadtxt cannot understand the contents of %s'+\
            'with the given arguments: %s', fname, **kwargs)
        raise
    except (IOError, FileNotFoundError):
        logger.critical('np.loadtxt cannot open %s', fname)
        raise
    # do some filtering on columns and/or rows if requested
    # note that file to 2D-array mapping depends on 'unpack' from
    # kwargs, which transposes the loaded array.
    postprocess = {'rm_columns': rm_columns, 'rm_rows': rm_rows}
    if not any(postprocess.values()):
        if 'unpack' in kwargs.keys() and kwargs['unpack']:
            # since 'unpack' transposes the array, now row index
            # in the original file is along axis 1, while column index
            # in the original file is along axis 0.
            key1, key2 = ['rm_columns', 'rm_rows']
        else:
            key1, key2 = ['rm_rows', 'rm_columns']
        for axis, key in enumerate([key1, key2]):
            rm_rngs = postprocess.get(key, [])
            if rm_rngs:
                indexes = []
                # flatten, combine and sort, then delete corresp. object
                for rng in get_ranges(rm_rngs):
                    indexes.extend(list(range(*rng)))
                indexes = list(set(indexes))
                indexes.sort()
                data = np.delete(data, obj=indexes, axis=axis)
    data = data * scale
    # this have to become more generic: database.update(dst.datakey, data)
    database[dst][datakey] = data


def substitute_parameters(implargs, database, templatefiles, options, **kwargs):
    """Substitute parameters (within implicit arguments) in given templates.
    """
    logger = implargs.get('logger', LOGGER)
    workroot = implargs.get('workroot', '.')
    iteration = implargs.get('iteration', None)
    parameters = implargs.get('parameters', None)
    if parameters is not None:
        try:
            # assume parameters are objects with names
            parnames = [p.name for p in parameters]
        except AttributeError:
            try:
                parnames = options['parnames']
            except AttributeError:
                logger.critical('No parameter names found. '\
                                'Cannot proceed with parameter substitution.')
                raise
        logger.debug("Substituting parameters for iteration %s in %s.",\
                     iteration, workroot)
        update_parameters(workroot, templatefiles, parameters, parnames,
                          **kwargs)


TASKDICT = {
    'set': substitute_parameters,
    'sub': substitute_parameters,
    'substitute': substitute_parameters,
    #
    'run': execute,
    'exe': execute,
    'execute': execute,
    #
    'get': get_model_data,
    'get_data': get_model_data,
    #
    'plot': skparplot,
    'plot_objectives': skparplot,
    }
