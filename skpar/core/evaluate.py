"""Evaluator engine of SKPAR."""
import os
import shutil
import numpy as np
from skpar.core.utils import get_logger, normalise
from skpar.core.tasks import initialise_tasks

LOGGER = get_logger(__name__)

DEFAULT_GLOBAL_COST_FUNC = "rms"

DEFAULT_CONFIG = {
    'workroot': None,
    'templatedir': None,
    'keepworkdirs': True,
}


def abserr(ref, model):
    """Return the per-element difference model and reference.
    """
    rr = np.asarray(ref)
    mm = np.asarray(model)
    assert rr.shape == mm.shape, (rr.shape, mm.shape)
    return mm - ref

def relerr(ref, model):
    """Return the per-element relative difference between model and reference.

    To handle cases where `ref` vanish, and possibly `model` vanish
    at the same time, we:

        * translate directly a vanishing absolute error into vanishing
          relative error (where both `ref` and `model` vanish.

        * take the model as a denominator, thus yielding 1, where
          `ref` vanishes but `model` is non zero
    """
    rr = np.asarray(ref)
    mm = np.asarray(model)
    # get deviations
    err = abserr(rr, mm)
    # fix the denominator
    denom = rr.copy()
    denom[rr == 0.] = mm[rr == 0.]
    # assert 0 absolute error even for 0 denominator
    rele = np.zeros(err.shape)
    rele[err != 0] = err[err != 0] / denom[err != 0]
    return rele

def cost_RMS(ref, model, weights, errf=abserr):
    """Return the weighted-RMS deviation"""
    assert np.asarray(ref).shape == np.asarray(model).shape
    assert np.asarray(ref).shape == np.asarray(weights).shape
    err2 = errf(ref, model) ** 2
    rms = np.sqrt(np.sum(weights*err2))
    return rms

def eval_objectives(objectives):
    """
    """
    fitness = np.array([objv() for objv in objectives])
    return fitness

# ----------------------------------------------------------------------
# Function mappers
# ----------------------------------------------------------------------
# use small letters for the function names; make sure
# the input parser coerces any capitalisation in advance

# cost functions
COSTF = {"rms": cost_RMS, }

# error types
ERRF = {"abs": abserr, "rel": relerr, "abserr": abserr, "relerr": relerr,}
# ----------------------------------------------------------------------


class Evaluator(object):
    """**Evaluator**

    The evaluator is the only thing visible to the optimiser.
    It has several things to do:

    1. Accept a list (or dict) of parameter values (or key-value pairs),
       and an iteration number (or a tuple: (e.g. generation,particle_index)).

    2. Update tasks (and underlying models) with new parameter values.

    3. Execute the tasks to obtain model data with the new parameters.

    4. Evaluate fitness for individual objectives.

    5. Evaluate global fitness (cost) and return the value. It may be
       good to also return the max error, to be used as a stopping criterion.

    """
    def __init__(self, objectives, tasklist, taskdict, config=None,
                 costf=COSTF[DEFAULT_GLOBAL_COST_FUNC], utopia=None,
                 verbose=False, **kwargs):
        self.objectives = objectives
        # Ideally refdb does not change; should be passed as an object
        # that contains get() and has().
        # This here is a temporary hack to make reference data available to
        # tasks, but not consistent with current implementation of objectives.
        self.refdb = {}
        for objv in objectives:
            self.refdb[objv.name] = objv.refdata
        self.weights = normalise([oo.weight for oo in objectives])
        self.tasklist = tasklist # list of name,options pairs
        self.taskdict = taskdict # name:function mapping
        self.tasks = []          # callable objectsdd
        self.config = config if config is not None else DEFAULT_CONFIG
        workroot = self.config['workroot']
        if workroot is not None:
            workroot = os.path.abspath(workroot)
            if not os.path.exists(workroot):
                os.makedirs(workroot)
        self.costf = costf
        if utopia is None:
            self.utopia = np.zeros(len(self.objectives))
        else:
            assert len(utopia) == len(objectives), (len(utopia), len(objectives))
            self.utopia = utopia
        self.verbose = verbose
        # configure logger
        self.logger = LOGGER
        if self.verbose:
            self.msg = self.logger.info
        else:
            self.msg = self.logger.debug
        # report objectives; these do not change over time
        for item in objectives:
            self.msg(item)

    def evaluate(self, parameters, iteration=None):
        """Evaluate the global fitness of a given point in parameter space.

        This is the only object accessible to the optimiser, therefore only
        two arguments can be passed.

        Args:
            parameters (list or dict): current point in design/parameter space
            iteration: (int or tupple): current iteration or current
                generation and individual index within generation

        Return:
            fitness (float): global fitness of the current design point
        """

        # Create individual working directory for each evaluation
        origdir = os.getcwd()
        workroot = self.config['workroot']
        if workroot is None:
            workdir = origdir
        else:
            workdir = get_workdir(iteration, workroot)
            create_workdir(workdir, self.config['templatedir'])

        # Initialise model database
        self.logger.info('Initialising ModelDataBase.')
        # modeldb may be something different than a dictionary, but
        # whatever object it is, should have get(), set(), has()
        # The point is that for every individual evaluation, we must
        # have individual model DB, so evaluations can be done in parallel.
        modeldb = {}
        # Wrap the environment in a single dict
        env = {'workroot': workdir, 'logger': self.logger,
                'parameters': parameters, 'iteration': iteration,}
        # Initialise tasks
        self.tasks = initialise_tasks(self.tasklist, self.taskdict),
        # Get new model data by executing the rest of the tasks
        for i, task in enumerate(self.tasks):
            os.chdir(workdir)
            try:
                task(env, modeldb)
            except:
                self.logger.critical('Evaluation FAILED at task %i:\n%s', i, task)
                raise

        # Evaluate individual fitness for each objective
        objvfitness = eval_objectives(self.objectives)
        ref = self.utopia
        # evaluate global fitness
        cost = self.costf(ref, objvfitness, self.weights)
        self.msg('{:<15s}: {}\n'.format('Overall cost', cost))

        # Remove particle specific working dir if not needed:
        if (not self.config['keepworkdirs']) and (workroot is not None):
            destroy_workdir(workdir)
        os.chdir(origdir)

        return np.atleast_1d(cost)

    def __call__(self, parameters, iteration=None):
        return self.evaluate(parameters, iteration)

    def __repr__(self):
        ss = []
        ss.append('Evaluator:')
        ss.append('\n-- Tasks:')
        ss.append('--------------------')
        for item in self.tasks:
            ss.append(item.__repr__())
        ss.append('\n-- Objectives:')
        ss.append('--------------------')
        for item in self.objectives:
            ss.append(item.__repr__())
        ss.append('\n-- Cost Func.:')
        ss.append('--------------------')
        ss.append(self.costf.__name__)
        return '\n'.join(ss)


def get_workdir(iteration, workroot):
    if workroot is None:
        workdir = None
    else:
        if iteration is None:
            myworkdir = 'noiter'
        else:
            try:
                myworkdir = '-'.join([str(it) for it in iteration])
            except TypeError:
                myworkdir = str(iteration)
        workdir = os.path.abspath(os.path.join(workroot, myworkdir))
    return workdir


def create_workdir(workdir, templatedir):
    if workdir is None:
        return
    if os.path.exists(workdir):
        shutil.rmtree(workdir)
    if templatedir is not None:
        shutil.copytree(templatedir, workdir, symlinks=True)
    else:
        os.mkdir(workdir)


def destroy_workdir(workdir):
    if workdir is not None:
        shutil.rmtree(workdir)
