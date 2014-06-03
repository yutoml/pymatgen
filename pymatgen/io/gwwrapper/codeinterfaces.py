"""
UNDER DEVELOPMENT
Classes for code interfaces.
Uses code specific GWworkflows defined in GWworkflows. These may also be moved into the code interface.
Eventually all code dependent methods used by the the gwwrapper should be contained in a class defined here
Currently working on the implementation for VASP and ABINIT.
The VASP GWworkflow is currently coded here directly this still needs to be moved to the GWWorkflows
A new implementation can be created from the New_Code template, the new class should be added to the get_code_interface
factory function at the end.
"""

from __future__ import division

__author__ = "Michiel van Setten"
__copyright__ = " "
__version__ = "0.9"
__maintainer__ = "Michiel van Setten"
__email__ = "mjvansetten@gmail.com"
__date__ = "May 2014"

import os
import shutil
import os.path

from abc import abstractproperty, abstractmethod, ABCMeta
from pymatgen.io.abinitio.netcdf import NetcdfReader
from pymatgen.io.vaspio.vasp_output import Vasprun
from pymatgen.core.units import Ha_to_eV
from pymatgen.io.gwwrapper.GWhelpers import is_converged, read_grid_from_file, s_name, expand_tests, store_conv_results
from pymatgen.io.gwwrapper.GWvaspinputsets import SingleVaspGWWork
from pymatgen.io.gwwrapper.GWworkflows import VaspGWFWWorkFlow, SingleAbinitGWWorkFlow
from pymatgen.io.gwwrapper.GWvaspinputsets import GWscDFTPrepVaspInputSet, GWDFTDiagVaspInputSet, \
    GWG0W0VaspInputSet

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))


class AbstractCodeInterface(object):
    """
    UNDER DEVELOPMENT
        Abstract base class for a code, defining the code specific methods that need to be implemented for a code
        to be able to use it in the AbinitioSpec wrapper.
        first step : GW output parsing
    """
    __metaclass__ = ABCMeta

    def __init__(self):
        self.converged = False
        self.grid = 0
        self.all_done = False
        self.workdir = None

    @abstractproperty
    def hartree_parameters(self):
        """
        information of the unit of the input parameters True for hartree, False for eV
        return bool
        """

    @abstractproperty
    def supported_methods(self):
        """
        returns a list of supported method for this code, should correspond to the possible jobs in spec['jobs']
        """

    @abstractproperty
    def conv_pars(self):
        """
        returns a dictionary with the parameter names of nbands and ecuteps
        """

    def conv_res_string(self, conv_res):
        """
        print a dictionary of the parameters that give a converged result the dictionary should contain keywords
        specific to the code, and values as they are interpreted by the code
        """
        string = str({self.conv_pars['nbands']: conv_res['values']['nbands'],
                      self.conv_pars['ecuteps']: conv_res['values']['ecuteps']})
        return string

    def test_methods(self, data):
        errors = []
        for job in data['jobs']:
            if job not in self.supported_methods:
                errors.append(job + ' is not supported')
        return errors

    @abstractmethod
    def read_convergence_data(self, data_dir):
        """
        Method read from the datafile in data_dir the convergence data.
        return dict
        """

    @abstractmethod
    def test(self, data):
        """
        test if there are inherent errors in the input in spec
        return warning, errors
        """

    @abstractmethod
    def excecute_flow(self, structure, spec_data):
        """
        excecute spec prepare input/jobfiles or submit to fw for a given structure
        for vasp the different jobs are created into a flow
        for abinit a flow is created using abinitio
        """

    @abstractmethod
    def store_results(self, name):
        """
        method to store the final results
        """


class VaspInterface(AbstractCodeInterface):
    """
    Code interface for VASP
    """
    @property
    def hartree_parameters(self):
        return False

    @property
    def supported_methods(self):
        return ['prep', 'G0W0', 'GW0', 'scGW']

    @property
    def conv_pars(self):
        return {'nbands': 'NBANDS', 'ecuteps': 'ENCUTGW'}

    def read_convergence_data(self, data_dir):
        results = {}
        if 'G0W0' in data_dir or 'GW0' in data_dir or 'scGW0' in data_dir:
            run = os.path.join(data_dir, 'vasprun.xml')
            kpoints = os.path.join(data_dir, 'IBZKPT')
            if os.path.isfile(run):
                try:
                    data = Vasprun(run, ionic_step_skip=1)
                    parameters = data.__getattribute__('incar').to_dict
                    bandstructure = data.get_band_structure(kpoints)
                    results = {'ecuteps': parameters['ENCUTGW'],
                               'nbands': parameters['NBANDS'],
                               'nomega': parameters['NOMEGA'],
                               'gwgap': bandstructure.get_band_gap()['energy']}
                except (IOError, OSError, IndexError, KeyError):
                    pass
        return results

    def test(self, data):
        warnings = []
        errors = []
        if data['converge']:
            warnings.append('converge defined for VASP, very early stage of development')
        if data['functional'] not in ['PBE', 'LDA']:
            errors.append(str(data['functional'] + ' not defined for VASP yet'))
        if 'prep' not in data['jobs']:
            warnings.append('no preparation job specified, this only makes sense for testing')
        errors.extend(self.test_methods(data))
        return warnings, errors

    def excecute_flow(self, structure, spec_data):
        """
        excecute spec prepare input/jobfiles or submit to fw for a given structure
        for vasp the different jobs are created into a flow
        todo this should actually create and excecute a VaspGWWorkFlow(GWWorkflow)
        """
        ### general part for the base class
        grid = 0
        all_done = False
        converged = is_converged(False, structure)
        try:
            grid = read_grid_from_file(s_name(structure)+".full_res")['grid']
            all_done = read_grid_from_file(s_name(structure)+".full_res")['all_done']
        except (IOError, OSError):
            pass

        if all_done:
            print '| all is done for this material'
            return

        ### specific part

        if spec_data['mode'] == 'fw':
            fw_work_flow = VaspGWFWWorkFlow()
        else:
            fw_work_flow = []
        if spec_data['test'] or spec_data['converge']:
            if spec_data['test']:
                tests_prep = GWscDFTPrepVaspInputSet(structure, spec_data).tests
                tests_prep.update(GWDFTDiagVaspInputSet(structure, spec_data).tests)
            elif spec_data['converge'] and converged:
                tests_prep = self.get_conv_res_test(spec_data, structure)['tests_prep']
            else:
                tests_prep = GWscDFTPrepVaspInputSet(structure, spec_data).convs
                tests_prep.update(GWDFTDiagVaspInputSet(structure, spec_data).convs)
                if grid > 0:
                    tests_prep = expand_tests(tests=tests_prep, level=grid)
                print tests_prep
            for test_prep in tests_prep:
                print 'setting up test for: ' + test_prep
                for value_prep in tests_prep[test_prep]['test_range']:
                    print "**" + str(value_prep) + "**"
                    option = {'test_prep': test_prep, 'value_prep': value_prep}
                    self.create_job(spec_data, structure, 'prep', fw_work_flow, converged, option)
                    for job in spec_data['jobs'][1:]:
                        if job == 'G0W0':
                            if spec_data['test']:
                                tests = GWG0W0VaspInputSet(structure, spec_data).tests
                            elif spec_data['converge'] and converged:
                                tests = self.get_conv_res_test(spec_data, structure)['tests']
                            else:
                                tests = GWG0W0VaspInputSet(structure, spec_data).convs
                                if grid > 0:
                                    tests = expand_tests(tests=tests, level=grid)
                                print tests
                        if job in ['GW0', 'scGW0']:
                            input_set = GWG0W0VaspInputSet(structure, spec_data)
                            input_set.gw0_on()
                            if spec_data['test']:
                                tests = input_set.tests
                            else:
                                tests = input_set.tests
                        for test in tests:
                            print '    setting up test for: ' + test
                            for value in tests[test]['test_range']:
                                print "    **" + str(value) + "**"
                                option.update({'test': test, 'value': value})
                                self.create_job(spec_data, structure, job, fw_work_flow, converged, option)

    @staticmethod
    def get_conv_res_test(spec_data, structure):
        """
        return test sets for the tests in test relative to the convergence results
        """
        tests_conv = {}
        tests_prep_conv = {}
        tests_prep = GWscDFTPrepVaspInputSet(structure, spec_data).tests
        tests_prep.update(GWDFTDiagVaspInputSet(structure, spec_data).tests)
        tests = GWG0W0VaspInputSet(structure, spec_data).tests
        conv_res = is_converged(spec_data, structure, return_values=True)
        for test in conv_res.keys():
            if test in tests_prep.keys():
                rel = tests_prep[test]['test_range'][1] - tests_prep[test]['test_range'][0]
                value = conv_res[test]
                tests_prep_conv.update({test: tests_prep[test]})
                tests_prep_conv[test].update({'test_range': (value, value + rel)})
            elif test in tests.keys():
                rel = tests[test]['test_range'][1] - tests[test]['test_range'][0]
                value = conv_res[test]
                tests_conv.update({test: tests[test]})
                tests_conv[test].update({'test_range': (value, value + rel)})
        return {'tests': tests_conv, 'tests_prep': tests_prep_conv}

    @staticmethod
    def create_job(spec_data, structure, job, fw_work_flow, converged, option=None):
        work = SingleVaspGWWork(structure, job, spec_data, option=option, converged=converged)
        if 'input' in spec_data['mode'] or 'ceci' in spec_data['mode']:
            work.create_input()
            if 'ceci' in spec_data['mode']:
                work.create_job_script()
        if 'fw' in spec_data['mode']:
            structure_dict = structure.to_dict
            band_structure_dict = {'vbm_l': structure.vbm_l, 'cbm_l': structure.cbm_l, 'vbm_a': structure.vbm[0],
                                   'vbm_b': structure.vbm[1], 'vbm_c': structure.vbm[2], 'cbm_a': structure.cbm[0],
                                   'cbm_b': structure.cbm[1], 'cbm_c': structure.cbm[2]}
            parameters = {'structure': structure_dict, 'band_structure': band_structure_dict, 'job': job,
                          'spec': spec_data, 'option': option}
            fw_work_flow.add_work(parameters)

    @staticmethod
    def get_npar(spec_data, structure):
        return GWG0W0VaspInputSet(structure, spec_data).get_npar(structure)

    def store_results(self, name):
        folder = name + '.res'
        store_conv_results(name, folder)
        #todo copy the final file containing the qp to folder
        raise NotImplementedError


class AbinitInterface(AbstractCodeInterface):
    """
    Code interface for ABINIT
    """
    @property
    def hartree_parameters(self):
        return True

    @property
    def supported_methods(self):
        return ['prep', 'G0W0']

    @property
    def conv_pars(self):
        return {'nbands': 'nscf_nbands', 'ecuteps': 'ecuteps'}

    other_vars = """
        [u'space_group', u'primitive_vectors', u'reduced_symmetry_matrices', u'reduced_symmetry_translations',
         u'atom_species', u'reduced_atom_positions', u'valence_charges', u'atomic_numbers', u'atom_species_names',
         u'chemical_symbols', u'pseudopotential_types', u'symafm', u'kpoint_grid_shift', u'kpoint_grid_vectors',
         u'monkhorst_pack_folding', u'reduced_coordinates_of_kpoints', u'kpoint_weights', u'number_of_electrons',
         u'exchange_functional', u'correlation_functional', u'fermi_energy', u'smearing_scheme', u'smearing_width',
          u'number_of_states', u'eigenvalues', u'occupations', u'tphysel', u'occopt', u'istwfk', u'shiftk',
         u'kptrlatt', u'ngkpt_shiftk', u'ecutwfn', u'ecuteps', u'ecutsigx', u'sigma_nband', u'gwcalctyp',
         u'omegasrdmax', u'deltae', u'omegasrmax', u'scissor_ene', u'usepawu', u'kptgw', u'minbnd', u'maxbnd',
         u'degwgap', u'egwgap', u'en_qp_diago', u'e0', u'e0gap', u'sigxme', u'vxcme', u'vUme', u'degw', u'dsigmee0',
         u'egw', u'eigvec_qp', u'hhartree', u'sigmee', u'sigcmee0', u'sigcmesi', u'sigcme4sd', u'sigxcme4sd',
         u'ze0', u'omega4sd'] for later use """

    def read_convergence_data(self, data_dir):
        gwrun = os.path.join(data_dir, 'out_SIGRES.nc')
        scfrun = os.path.join(data_dir, 'out_OUT.nc')
        results = {}
        if os.path.isfile(gwrun):
            # return the gap at gamma
            data = NetcdfReader(gwrun)
            data.print_tree()
            results = {'ecuteps': Ha_to_eV * data.read_value('ecuteps')[0],
                       'nbands': data.read_value('sigma_nband')[0],
                       'gwgap': data.read_value('egwgap')[0][0]}
            data.close()
            return results
        if os.path.isfile(scfrun):
            # return the lowest and hightest eigenvalue at gamma
            data = NetcdfReader(scfrun)
            out = NetcdfReader('out_OUT.nc')
            results = {'ecut': Ha_to_eV * out.read_value('ecut')[0],
                       'min': data.read_value('Eigenvalues')[0][0][0],
                       'max': data.read_value('Eigenvalues')[0][0][-1]}
            data.close()
            print 'devel: ', results
            return results

    def test(self, data):
        errors = []
        warnings = []
        if data['converge']:
            warnings.append('converge defined for abinit, still under development')
        if data['functional'] not in ['PBE']:
            errors.append(str(data['functional'] + 'not defined for ABINIT yet'))
        errors.extend(self.test_methods(data))
        return warnings, errors

    def excecute_flow(self, structure, spec_data):
        """
        excecute spec prepare input/jobfiles or submit to fw for a given structure
        for abinit a flow is created using abinitio
        """
        if spec_data['converge'] and is_converged(spec_data, structure):
            option = is_converged(spec_data, structure, return_values=True)
        else:
            option = None
        work_flow = SingleAbinitGWWorkFlow(structure, spec_data, option)
        flow = work_flow.create()
        if flow is not None:
            flow.build_and_pickle_dump()
            work_flow.create_job_file()

    def store_results(self, name):
        folder = name + '.res'
        store_conv_results(name, folder)
        try:
            shutil.copyfile(os.path.join(name+".conv", "w0", "t6", "outdata", "out_SIGRES.nc"),
                        os.path.join(folder, "out_SIGRES.nc"))
        except:  # compatibility issue
            shutil.copyfile(os.path.join(name+".conv", "work_0", "task_6", "outdata", "out_SIGRES.nc"),
                        os.path.join(folder, "out_SIGRES.nc"))


class NewCodeInterface(AbstractCodeInterface):
    """
    Template for creating a code interface for a new code
    """
    @property
    def hartree_parameters(self):
        return False  # adapt: true is input parameters are in hartree, false for eV

    @property
    def supported_methods(self):
        return ['method1', 'method2']

    @property
    def conv_pars(self):
        return {'nbands': 'new_code_nbands', 'ecuteps': 'new_code_nbands'}

    # methods for data parsing

    def read_convergence_data(self, data_dir):
        results = {}  # adapt to read the output of NEW_CODE
        raise NotImplementedError
        return results

    def test(self, data):
        """
        test if there are inherent errors in the input in spec
        return warning, errors
        """
        errors = []
        warnings = []
        errors.extend(self.test_methods(data))

    def excecute_flow(self, structure, spec_data):
        """
        excecute spec prepare input/jobfiles or submit to fw for a given structure
        here either an method is implemented that creates the flow, like vasp, or a flow is created from a class,
        like in abinit
        """

    def store_results(self, name):
        folder = name + '.res'
        store_conv_results(name, folder)
        # copy the final file containing the qp to folder



CODE_CLASSES = {'VASP': VaspInterface,
                'ABINIT': AbinitInterface,
                'NEW_CODE': NewCodeInterface}


def get_code_interface(code):
    """
    Factory function to return a code interface object
    """
    if code not in CODE_CLASSES.keys():
        raise NotImplementedError
    return CODE_CLASSES[code]()


def get_all_nbands():
    nband_names = []
    for code in CODE_CLASSES.values():
        conv_pars = code().conv_pars
        nband_names.append(conv_pars['nbands'])
    return nband_names


def get_all_ecuteps():
    ecuteps_names = []
    for code in CODE_CLASSES.values():
        conv_pars = code().conv_pars
        ecuteps_names.append(conv_pars['ecuteps'])
    return ecuteps_names

