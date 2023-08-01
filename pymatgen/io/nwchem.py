"""
This module implements input and output processing from Nwchem.

2015/09/21 - Xin Chen (chenxin13@mails.tsinghua.edu.cn):

    NwOutput will read new kinds of data:

        1. normal hessian matrix.       ["hessian"]
        2. projected hessian matrix.    ["projected_hessian"]
        3. normal frequencies.          ["normal_frequencies"]

    For backward compatibility, the key for accessing the projected frequencies
    is still 'frequencies'.

2015/10/12 - Xin Chen
    NwOutput will read new kinds of data:

        1. forces.                      ["forces"]
"""

from __future__ import annotations

import os
import re
import warnings
from string import Template

import numpy as np
from monty.io import zopen
from monty.json import MSONable

from pymatgen.analysis.excitation import ExcitationSpectrum
from pymatgen.core.structure import Molecule, Structure
from pymatgen.core.units import Energy, FloatWithUnit

NWCHEM_BASIS_LIBRARY = None
if os.getenv("NWCHEM_BASIS_LIBRARY"):
    NWCHEM_BASIS_LIBRARY = set(os.listdir(os.environ["NWCHEM_BASIS_LIBRARY"]))


class NwTask(MSONable):
    """Base task for Nwchem."""

    theories = {
        "g3gn": "some description",
        "scf": "Hartree-Fock",
        "dft": "DFT",
        "esp": "ESP",
        "sodft": "Spin-Orbit DFT",
        "mp2": "MP2 using a semi-direct algorithm",
        "direct_mp2": "MP2 using a full-direct algorithm",
        "rimp2": "MP2 using the RI approximation",
        "ccsd": "Coupled-cluster single and double excitations",
        "ccsd(t)": "Coupled-cluster linearized triples approximation",
        "ccsd+t(ccsd)": "Fourth order triples contribution",
        "mcscf": "Multiconfiguration SCF",
        "selci": "Selected CI with perturbation correction",
        "md": "Classical molecular dynamics simulation",
        "pspw": "Pseudopotential plane-wave DFT for molecules and insulating solids using NWPW",
        "band": "Pseudopotential plane-wave DFT for solids using NWPW",
        "tce": "Tensor Contraction Engine",
        "tddft": "Time Dependent DFT",
    }

    operations = {
        "energy": "Evaluate the single point energy.",
        "gradient": "Evaluate the derivative of the energy with respect to nuclear coordinates.",
        "optimize": "Minimize the energy by varying the molecular structure.",
        "saddle": "Conduct a search for a transition state (or saddle point).",
        "hessian": "Compute second derivatives.",
        "frequencies": "Compute second derivatives and print out an analysis of molecular vibrations.",
        "freq": "Same as frequencies.",
        "vscf": "Compute anharmonic contributions to the vibrational modes.",
        "property": "Calculate the properties for the wave function.",
        "dynamics": "Perform classical molecular dynamics.",
        "thermodynamics": "Perform multi-configuration thermodynamic integration using classical MD.",
        "": "dummy",
    }

    def __init__(
        self,
        charge,
        spin_multiplicity,
        basis_set,
        basis_set_option="cartesian",
        title=None,
        theory="dft",
        operation="optimize",
        theory_directives=None,
        alternate_directives=None,
    ):
        """
        Very flexible arguments to support many types of potential setups.
        Users should use more friendly static methods unless they need the
        flexibility.

        Args:
            charge: Charge of the molecule. If None, charge on molecule is
                used. Defaults to None. This allows the input file to be set a
                charge independently from the molecule itself.
            spin_multiplicity: Spin multiplicity of molecule. Defaults to None,
                which means that the spin multiplicity is set to 1 if the
                molecule has no unpaired electrons and to 2 if there are
                unpaired electrons.
            basis_set: The basis set used for the task as a dict. E.g.,
                {"C": "6-311++G**", "H": "6-31++G**"}.
            basis_set_option: cartesian (default) | spherical,
            title: Title for the task. Defaults to None, which means a title
                based on the theory and operation of the task is
                autogenerated.
            theory: The theory used for the task. Defaults to "dft".
            operation: The operation for the task. Defaults to "optimize".
            theory_directives: A dict of theory directives. For example,
                if you are running dft calculations, you may specify the
                exchange correlation functional using {"xc": "b3lyp"}.
            alternate_directives: A dict of alternate directives. For
                example, to perform cosmo calculations and dielectric
                constant of 78, you'd supply {'cosmo': {"dielectric": 78}}.
        """
        # Basic checks.
        if theory.lower() not in NwTask.theories:
            raise NwInputError(f"Invalid {theory=}")

        if operation.lower() not in NwTask.operations:
            raise NwInputError(f"Invalid {operation=}")
        self.charge = charge
        self.spin_multiplicity = spin_multiplicity
        self.title = title if title is not None else f"{theory} {operation}"
        self.theory = theory

        self.basis_set = basis_set or {}
        if NWCHEM_BASIS_LIBRARY is not None:
            for b in set(self.basis_set.values()):
                if re.sub(r"\*", "s", b.lower()) not in NWCHEM_BASIS_LIBRARY:
                    warnings.warn(f"Basis set {b} not in in NWCHEM_BASIS_LIBRARY")

        self.basis_set_option = basis_set_option

        self.operation = operation
        self.theory_directives = theory_directives or {}
        self.alternate_directives = alternate_directives or {}

    def __str__(self):
        bset_spec = []
        for el, bset in sorted(self.basis_set.items(), key=lambda x: x[0]):
            bset_spec.append(f' {el} library "{bset}"')
        theory_spec = []
        if self.theory_directives:
            theory_spec.append(f"{self.theory}")
            for k in sorted(self.theory_directives):
                theory_spec.append(f" {k} {self.theory_directives[k]}")
            theory_spec.append("end")
        for k in sorted(self.alternate_directives):
            theory_spec.append(k)
            for k2 in sorted(self.alternate_directives[k]):
                theory_spec.append(f" {k2} {self.alternate_directives[k][k2]}")
            theory_spec.append("end")

        t = Template(
            """title "$title"
charge $charge
basis $basis_set_option
$bset_spec
end
$theory_spec
"""
        )

        output = t.substitute(
            title=self.title,
            charge=int(self.charge),
            spinmult=self.spin_multiplicity,
            basis_set_option=self.basis_set_option,
            bset_spec="\n".join(bset_spec),
            theory_spec="\n".join(theory_spec),
            theory=self.theory,
        )

        if self.operation is not None:
            output += f"task {self.theory} {self.operation}"
        return output

    def as_dict(self):
        """Returns: MSONable dict."""
        return {
            "@module": type(self).__module__,
            "@class": type(self).__name__,
            "charge": self.charge,
            "spin_multiplicity": self.spin_multiplicity,
            "title": self.title,
            "theory": self.theory,
            "operation": self.operation,
            "basis_set": self.basis_set,
            "basis_set_option": self.basis_set_option,
            "theory_directives": self.theory_directives,
            "alternate_directives": self.alternate_directives,
        }

    @classmethod
    def from_dict(cls, d):
        """
        Args:
            d (dict): Dict representation.

        Returns:
            NwTask
        """
        return NwTask(
            charge=d["charge"],
            spin_multiplicity=d["spin_multiplicity"],
            title=d["title"],
            theory=d["theory"],
            operation=d["operation"],
            basis_set=d["basis_set"],
            basis_set_option=d["basis_set_option"],
            theory_directives=d["theory_directives"],
            alternate_directives=d["alternate_directives"],
        )

    @classmethod
    def from_molecule(
        cls,
        mol,
        theory,
        charge=None,
        spin_multiplicity=None,
        basis_set="6-31g",
        basis_set_option="cartesian",
        title=None,
        operation="optimize",
        theory_directives=None,
        alternate_directives=None,
    ):
        """
        Very flexible arguments to support many types of potential setups.
        Users should use more friendly static methods unless they need the
        flexibility.

        Args:
            mol: Input molecule
            charge: Charge of the molecule. If None, charge on molecule is
                used. Defaults to None. This allows the input file to be set a
                charge independently from the molecule itself.
            spin_multiplicity: Spin multiplicity of molecule. Defaults to None,
                which means that the spin multiplicity is set to 1 if the
                molecule has no unpaired electrons and to 2 if there are
                unpaired electrons.
            basis_set: The basis set to be used as string or a dict. E.g.,
                {"C": "6-311++G**", "H": "6-31++G**"} or "6-31G". If string,
                same basis set is used for all elements.
            basis_set_option: cartesian (default) | spherical,
            title: Title for the task. Defaults to None, which means a title
                based on the theory and operation of the task is
                autogenerated.
            theory: The theory used for the task. Defaults to "dft".
            operation: The operation for the task. Defaults to "optimize".
            theory_directives: A dict of theory directives. For example,
                if you are running dft calculations, you may specify the
                exchange correlation functional using {"xc": "b3lyp"}.
            alternate_directives: A dict of alternate directives. For
                example, to perform cosmo calculations with DFT, you'd supply
                {'cosmo': "cosmo"}.
        """
        formula = re.sub(r"\s", "", mol.formula)
        title = title if title is not None else f"{formula} {theory} {operation}"

        charge = charge if charge is not None else mol.charge
        n_electrons = -charge + mol.charge + mol.nelectrons  # pylint: disable=E1130
        if spin_multiplicity is not None:
            if (n_electrons + spin_multiplicity) % 2 != 1:
                raise ValueError(f"{charge=} and {spin_multiplicity=} is not possible for this molecule")
        elif charge == mol.charge:
            spin_multiplicity = mol.spin_multiplicity
        else:
            spin_multiplicity = 1 if n_electrons % 2 == 0 else 2

        elements = set(mol.composition.get_el_amt_dict())
        if isinstance(basis_set, str):
            basis_set = {el: basis_set for el in elements}

        return NwTask(
            charge,
            spin_multiplicity,
            basis_set,
            basis_set_option=basis_set_option,
            title=title,
            theory=theory,
            operation=operation,
            theory_directives=theory_directives,
            alternate_directives=alternate_directives,
        )

    @classmethod
    def dft_task(cls, mol, xc="b3lyp", **kwargs):
        """
        A class method for quickly creating DFT tasks with optional
        cosmo parameter .

        Args:
            mol: Input molecule
            xc: Exchange correlation to use.
            kwargs: Any of the other kwargs supported by NwTask. Note the
                theory is always "dft" for a dft task.
        """
        t = NwTask.from_molecule(mol, theory="dft", **kwargs)
        t.theory_directives.update({"xc": xc, "mult": t.spin_multiplicity})
        return t

    @classmethod
    def esp_task(cls, mol, **kwargs):
        """
        A class method for quickly creating ESP tasks with RESP
        charge fitting.

        Args:
            mol: Input molecule
            kwargs: Any of the other kwargs supported by NwTask. Note the
                theory is always "dft" for a dft task.
        """
        return NwTask.from_molecule(mol, theory="esp", **kwargs)


class NwInput(MSONable):
    """
    An object representing a Nwchem input file, which is essentially a list
    of tasks on a particular molecule.
    """

    def __init__(
        self,
        mol,
        tasks,
        directives=None,
        geometry_options=("units", "angstroms"),
        symmetry_options=None,
        memory_options=None,
    ):
        """
        Args:
            mol: Input molecule. If molecule is a single string, it is used as a
                direct input to the geometry section of the Gaussian input
                file.
            tasks: List of NwTasks.
            directives: List of root level directives as tuple. E.g.,
                [("start", "water"), ("print", "high")]
            geometry_options: Additional list of options to be supplied to the
                geometry. E.g., ["units", "angstroms", "noautoz"]. Defaults to
                ("units", "angstroms").
            symmetry_options: Addition list of option to be supplied to the
                symmetry. E.g. ["c1"] to turn off the symmetry
            memory_options: Memory controlling options. str.
                E.g "total 1000 mb stack 400 mb".
        """
        self._mol = mol
        self.directives = directives if directives is not None else []
        self.tasks = tasks
        self.geometry_options = geometry_options
        self.symmetry_options = symmetry_options
        self.memory_options = memory_options

    @property
    def molecule(self):
        """Returns molecule associated with this GaussianInput."""
        return self._mol

    def __str__(self):
        o = []
        if self.memory_options:
            o.append("memory " + self.memory_options)
        for d in self.directives:
            o.append(f"{d[0]} {d[1]}")
        o.append("geometry " + " ".join(self.geometry_options))
        if self.symmetry_options:
            o.append(" symmetry " + " ".join(self.symmetry_options))
        for site in self._mol:
            o.append(f" {site.specie.symbol} {site.x} {site.y} {site.z}")
        o.append("end\n")
        for t in self.tasks:
            o.append(str(t))
            o.append("")
        return "\n".join(o)

    def write_file(self, filename):
        """
        Args:
            filename (str): Filename.
        """
        with zopen(filename, "w") as f:
            f.write(str(self))

    def as_dict(self):
        """Returns: MSONable dict."""
        return {
            "mol": self._mol.as_dict(),
            "tasks": [t.as_dict() for t in self.tasks],
            "directives": [list(t) for t in self.directives],
            "geometry_options": list(self.geometry_options),
            "symmetry_options": self.symmetry_options,
            "memory_options": self.memory_options,
        }

    @classmethod
    def from_dict(cls, d):
        """
        Args:
            d (dict): Dict representation.

        Returns:
            NwInput
        """
        return NwInput(
            Molecule.from_dict(d["mol"]),
            tasks=[NwTask.from_dict(dt) for dt in d["tasks"]],
            directives=[tuple(li) for li in d["directives"]],
            geometry_options=d["geometry_options"],
            symmetry_options=d["symmetry_options"],
            memory_options=d["memory_options"],
        )

    @classmethod
    @np.deprecate(message="Use from_str instead")
    def from_string(cls, *args, **kwargs):
        return cls.from_str(*args, **kwargs)

    @classmethod
    def from_str(cls, string_input):
        """
        Read an NwInput from a string. Currently tested to work with
        files generated from this class itself.

        Args:
            string_input: string_input to parse.

        Returns:
            NwInput object
        """
        directives = []
        tasks = []
        charge = spin_multiplicity = title = basis_set = None
        basis_set_option = None
        theory_directives = {}
        geom_options = symmetry_options = memory_options = None
        lines = string_input.strip().split("\n")
        while len(lines) > 0:
            line = lines.pop(0).strip()
            if line == "":
                continue

            toks = line.split()
            if toks[0].lower() == "geometry":
                geom_options = toks[1:]
                line = lines.pop(0).strip()
                toks = line.split()
                if toks[0].lower() == "symmetry":
                    symmetry_options = toks[1:]
                    line = lines.pop(0).strip()
                # Parse geometry
                species = []
                coords = []
                while line.lower() != "end":
                    toks = line.split()
                    species.append(toks[0])
                    coords.append([float(i) for i in toks[1:]])
                    line = lines.pop(0).strip()
                mol = Molecule(species, coords)
            elif toks[0].lower() == "charge":
                charge = int(toks[1])
            elif toks[0].lower() == "title":
                title = line[5:].strip().strip('"')
            elif toks[0].lower() == "basis":
                # Parse basis sets
                line = lines.pop(0).strip()
                basis_set = {}
                while line.lower() != "end":
                    toks = line.split()
                    basis_set[toks[0]] = toks[-1].strip('"')
                    line = lines.pop(0).strip()
            elif toks[0].lower() in NwTask.theories:
                # read the basis_set_option
                if len(toks) > 1:
                    basis_set_option = toks[1]
                # Parse theory directives.
                theory = toks[0].lower()
                line = lines.pop(0).strip()
                theory_directives[theory] = {}
                while line.lower() != "end":
                    toks = line.split()
                    theory_directives[theory][toks[0]] = toks[-1]
                    if toks[0] == "mult":
                        spin_multiplicity = float(toks[1])
                    line = lines.pop(0).strip()
            elif toks[0].lower() == "task":
                tasks.append(
                    NwTask(
                        charge=charge,
                        spin_multiplicity=spin_multiplicity,
                        title=title,
                        theory=toks[1],
                        operation=toks[2],
                        basis_set=basis_set,
                        basis_set_option=basis_set_option,
                        theory_directives=theory_directives.get(toks[1]),
                    )
                )
            elif toks[0].lower() == "memory":
                memory_options = " ".join(toks[1:])
            else:
                directives.append(line.strip().split())

        return NwInput(
            mol,
            tasks=tasks,
            directives=directives,
            geometry_options=geom_options,
            symmetry_options=symmetry_options,
            memory_options=memory_options,
        )

    @classmethod
    def from_file(cls, filename):
        """
        Read an NwInput from a file. Currently tested to work with
        files generated from this class itself.

        Args:
            filename: Filename to parse.

        Returns:
            NwInput object
        """
        with zopen(filename) as f:
            return cls.from_str(f.read())


class NwInputError(Exception):
    """Error class for NwInput."""


class NwOutput:
    """
    A Nwchem output file parser. Very basic for now - supports only dft and
    only parses energies and geometries. Please note that Nwchem typically
    outputs energies in either au or kJ/mol. All energies are converted to
    eV in the parser.
    """

    def __init__(self, filename):
        """
        Args:
            filename: Filename to read.
        """
        self.filename = filename

        with zopen(filename) as f:
            data = f.read()

        chunks = re.split(r"NWChem Input Module", data)
        if re.search(r"CITATION", chunks[-1]):
            chunks.pop()
        preamble = chunks.pop(0)

        self.raw = data
        self.job_info = self._parse_preamble(preamble)
        self.data = [self._parse_job(c) for c in chunks]

    def parse_tddft(self):
        """
        Parses TDDFT roots. Adapted from nw_spectrum.py script.

        Returns:
            {
                "singlet": [
                    {
                        "energy": float,
                        "osc_strength: float
                    }
                ],
                "triplet": [
                    {
                        "energy": float
                    }
                ]
            }
        """
        start_tag = "Convergence criterion met"
        end_tag = "Excited state energy"
        singlet_tag = "singlet excited"
        triplet_tag = "triplet excited"
        state = "singlet"
        inside = False  # true when we are inside output block

        lines = self.raw.split("\n")

        roots = {"singlet": [], "triplet": []}

        while lines:
            line = lines.pop(0).strip()

            if start_tag in line:
                inside = True

            elif end_tag in line:
                inside = False

            elif singlet_tag in line:
                state = "singlet"

            elif triplet_tag in line:
                state = "triplet"

            elif inside and "Root" in line and "eV" in line:
                toks = line.split()
                roots[state].append({"energy": float(toks[-2])})

            elif inside and "Dipole Oscillator Strength" in line:
                osc = float(line.split()[-1])
                roots[state][-1]["osc_strength"] = osc

        return roots

    def get_excitation_spectrum(self, width=0.1, npoints=2000):
        """
        Generate an excitation spectra from the singlet roots of TDDFT
        calculations.

        Args:
            width (float): Width for Gaussian smearing.
            npoints (int): Number of energy points. More points => smoother
                curve.

        Returns:
            (ExcitationSpectrum) which can be plotted using
                pymatgen.vis.plotters.SpectrumPlotter.
        """
        roots = self.parse_tddft()
        data = roots["singlet"]
        en = np.array([d["energy"] for d in data])
        osc = np.array([d["osc_strength"] for d in data])

        epad = 20.0 * width
        emin = en[0] - epad
        emax = en[-1] + epad
        de = (emax - emin) / npoints

        # Use width of at least two grid points
        if width < 2 * de:
            width = 2 * de

        energies = [emin + ie * de for ie in range(npoints)]

        cutoff = 20.0 * width
        gamma = 0.5 * width
        gamma_sqrd = gamma * gamma

        de = (energies[-1] - energies[0]) / (len(energies) - 1)
        prefac = gamma / np.pi * de

        x = []
        y = []
        for energy in energies:
            xx0 = energy - en
            stot = osc / (xx0 * xx0 + gamma_sqrd)
            t = np.sum(stot[np.abs(xx0) <= cutoff])
            x.append(energy)
            y.append(t * prefac)
        return ExcitationSpectrum(x, y)

    @staticmethod
    def _parse_preamble(preamble):
        info = {}
        for line in preamble.split("\n"):
            toks = line.split("=")
            if len(toks) > 1:
                info[toks[0].strip()] = toks[-1].strip()
        return info

    def __iter__(self):
        return self.data.__iter__()

    def __getitem__(self, ind):
        return self.data[ind]

    def __len__(self):
        return len(self.data)

    @staticmethod
    def _parse_job(output):
        energy_patt = re.compile(r"Total \w+ energy\s+=\s+([.\-\d]+)")
        energy_gas_patt = re.compile(r"gas phase energy\s+=\s+([.\-\d]+)")
        energy_sol_patt = re.compile(r"sol phase energy\s+=\s+([.\-\d]+)")
        coord_patt = re.compile(r"\d+\s+(\w+)\s+[.\-\d]+\s+([.\-\d]+)\s+([.\-\d]+)\s+([.\-\d]+)")
        lat_vector_patt = re.compile(r"a[123]=<\s+([.\-\d]+)\s+([.\-\d]+)\s+([.\-\d]+)\s+>")
        corrections_patt = re.compile(r"([\w\-]+ correction to \w+)\s+=\s+([.\-\d]+)")
        preamble_patt = re.compile(
            r"(No. of atoms|No. of electrons|SCF calculation type|Charge|Spin multiplicity)\s*:\s*(\S+)"
        )
        force_patt = re.compile(r"\s+(\d+)\s+(\w+)" + 6 * r"\s+([0-9\.\-]+)")

        time_patt = re.compile(r"\s+ Task \s+ times \s+ cpu: \s+   ([.\d]+)s .+ ", re.VERBOSE)

        error_defs = {
            "calculations not reaching convergence": "Bad convergence",
            "Calculation failed to converge": "Bad convergence",
            "geom_binvr: #indep variables incorrect": "autoz error",
            "dft optimize failed": "Geometry optimization failed",
        }

        def fort2py(x):
            return x.replace("D", "e")

        def isfloatstring(s):
            return s.find(".") == -1

        parse_hess = False
        parse_proj_hess = False
        hessian = projected_hessian = None
        parse_force = False
        all_forces = []
        forces = []

        data = {}
        energies = []
        frequencies = normal_frequencies = None
        corrections = {}
        molecules = []
        structures = []
        species = []
        coords = []
        lattice = []
        errors = []
        basis_set = {}
        bset_header = []
        parse_geom = False
        parse_freq = False
        parse_bset = False
        parse_projected_freq = False
        job_type = ""
        parse_time = False
        time = 0

        for line in output.split("\n"):
            # pylint: disable=E1136
            for e, v in error_defs.items():
                if line.find(e) != -1:
                    errors.append(v)
            if parse_time:
                m = time_patt.search(line)
                if m:
                    time = m.group(1)
                    parse_time = False
            if parse_geom:
                if line.strip() == "Atomic Mass":
                    if lattice:
                        structures.append(Structure(lattice, species, coords, coords_are_cartesian=True))
                    else:
                        molecules.append(Molecule(species, coords))
                    species = []
                    coords = []
                    lattice = []
                    parse_geom = False
                else:
                    m = coord_patt.search(line)
                    if m:
                        species.append(m.group(1).capitalize())
                        coords.append([float(m.group(2)), float(m.group(3)), float(m.group(4))])
                    m = lat_vector_patt.search(line)
                    if m:
                        lattice.append([float(m.group(1)), float(m.group(2)), float(m.group(3))])

            if parse_force:
                m = force_patt.search(line)
                if m:
                    forces.extend(map(float, m.groups()[5:]))
                elif len(forces) > 0:
                    all_forces.append(forces)
                    forces = []
                    parse_force = False

            elif parse_freq:
                if len(line.strip()) == 0:
                    if len(normal_frequencies[-1][1]) == 0:
                        continue
                    parse_freq = False
                else:
                    vibs = [float(vib) for vib in line.strip().split()[1:]]
                    num_vibs = len(vibs)
                    for mode, dis in zip(normal_frequencies[-num_vibs:], vibs):
                        mode[1].append(dis)

            elif parse_projected_freq:
                if len(line.strip()) == 0:
                    if len(frequencies[-1][1]) == 0:
                        continue
                    parse_projected_freq = False
                else:
                    vibs = [float(vib) for vib in line.strip().split()[1:]]
                    num_vibs = len(vibs)
                    for mode, dis in zip(frequencies[-num_vibs:], vibs):
                        mode[1].append(dis)

            elif parse_bset:
                if line.strip() == "":
                    parse_bset = False
                else:
                    toks = line.split()
                    if toks[0] != "Tag" and not re.match(r"-+", toks[0]):
                        basis_set[toks[0]] = dict(zip(bset_header[1:], toks[1:]))
                    elif toks[0] == "Tag":
                        bset_header = toks
                        bset_header.pop(4)
                        bset_header = [h.lower() for h in bset_header]

            elif parse_hess:
                if line.strip() == "":
                    continue
                if len(hessian) > 0 and line.find("----------") != -1:
                    parse_hess = False
                    continue
                toks = line.strip().split()
                if len(toks) > 1:
                    try:
                        row = int(toks[0])
                    except Exception:
                        continue
                    if isfloatstring(toks[1]):
                        continue
                    vals = [float(fort2py(x)) for x in toks[1:]]
                    if len(hessian) < row:
                        hessian.append(vals)
                    else:
                        hessian[row - 1].extend(vals)

            elif parse_proj_hess:
                if line.strip() == "":
                    continue
                nat3 = len(hessian)
                toks = line.strip().split()
                if len(toks) > 1:
                    try:
                        row = int(toks[0])
                    except Exception:
                        continue
                    if isfloatstring(toks[1]):
                        continue
                    vals = [float(fort2py(x)) for x in toks[1:]]
                    if len(projected_hessian) < row:
                        projected_hessian.append(vals)
                    else:
                        projected_hessian[row - 1].extend(vals)
                    if len(projected_hessian[-1]) == nat3:
                        parse_proj_hess = False

            else:
                m = energy_patt.search(line)
                if m:
                    energies.append(Energy(m.group(1), "Ha").to("eV"))
                    parse_time = True
                    continue

                m = energy_gas_patt.search(line)
                if m:
                    cosmo_scf_energy = energies[-1]
                    energies[-1] = {}
                    energies[-1].update({"cosmo scf": cosmo_scf_energy})
                    energies[-1].update({"gas phase": Energy(m.group(1), "Ha").to("eV")})

                m = energy_sol_patt.search(line)
                if m:
                    energies[-1].update({"sol phase": Energy(m.group(1), "Ha").to("eV")})

                m = preamble_patt.search(line)
                if m:
                    try:
                        val = int(m.group(2))
                    except ValueError:
                        val = m.group(2)
                    k = m.group(1).replace("No. of ", "n").replace(" ", "_")
                    data[k.lower()] = val
                elif line.find('Geometry "geometry"') != -1:
                    parse_geom = True
                elif line.find('Summary of "ao basis"') != -1:
                    parse_bset = True
                elif line.find("P.Frequency") != -1:
                    parse_projected_freq = True
                    if frequencies is None:
                        frequencies = []
                    toks = line.strip().split()[1:]
                    frequencies.extend([(float(freq), []) for freq in toks])

                elif line.find("Frequency") != -1:
                    toks = line.strip().split()
                    if len(toks) > 1 and toks[0] == "Frequency":
                        parse_freq = True
                        if normal_frequencies is None:
                            normal_frequencies = []
                        normal_frequencies.extend([(float(freq), []) for freq in line.strip().split()[1:]])

                elif line.find("MASS-WEIGHTED NUCLEAR HESSIAN") != -1:
                    parse_hess = True
                    if not hessian:
                        hessian = []
                elif line.find("MASS-WEIGHTED PROJECTED HESSIAN") != -1:
                    parse_proj_hess = True
                    if not projected_hessian:
                        projected_hessian = []

                elif line.find("atom               coordinates                        gradient") != -1:
                    parse_force = True

                elif job_type == "" and line.strip().startswith("NWChem"):
                    job_type = line.strip()
                    if job_type == "NWChem DFT Module" and "COSMO solvation results" in output:
                        job_type += " COSMO"
                else:
                    m = corrections_patt.search(line)
                    if m:
                        corrections[m.group(1)] = FloatWithUnit(m.group(2), "kJ mol^-1").to("eV atom^-1")

        if frequencies:
            for _freq, mode in frequencies:
                mode[:] = zip(*[iter(mode)] * 3)
        if normal_frequencies:
            for _freq, mode in normal_frequencies:
                mode[:] = zip(*[iter(mode)] * 3)
        if hessian:
            n = len(hessian)
            for i in range(n):
                for j in range(i + 1, n):
                    hessian[i].append(hessian[j][i])
        if projected_hessian:
            n = len(projected_hessian)
            for i in range(n):
                for j in range(i + 1, n):
                    projected_hessian[i].append(projected_hessian[j][i])

        data.update(
            {
                "job_type": job_type,
                "energies": energies,
                "corrections": corrections,
                "molecules": molecules,
                "structures": structures,
                "basis_set": basis_set,
                "errors": errors,
                "has_error": len(errors) > 0,
                "frequencies": frequencies,
                "normal_frequencies": normal_frequencies,
                "hessian": hessian,
                "projected_hessian": projected_hessian,
                "forces": all_forces,
                "task_time": time,
            }
        )

        return data
