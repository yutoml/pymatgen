# coding: utf-8
# Copyright (c) Pymatgen Development Team.
# Distributed under the terms of the MIT License.
"""
Classes for writing XTB input files
"""
import logging
from typing import Dict, Optional, Union, List

from monty.json import MSONable
from pymatgen.core import Molecule

__author__ = "Alex Epstein"
__copyright__ = "Copyright 2020, The Materials Project"
__version__ = "0.1"
__maintainer__ = "Alex Epstein"
__email__ = "aepstein@lbl.gov"
__credits__ = "Sam Blau, Evan Spotte-Smith"

logger = logging.getLogger(__name__)


class CRESTInput(MSONable):
    """
    An object representing  CREST input files.
    Because CREST is controlled through command line flags and external
    files, the CRESTInput class mainly consists of methods for containing
    and writing external files.
    """

    def __init__(
        self,
        molecule: Molecule,
        coords_filename: Optional[str] = "crest_in.xyz",
        constraints: Optional[Dict[str, Union[List[int], float]]] = None,
    ):
        """

        :param molecule (pymatgen Molecule object):
            Input molecule, the only required CREST input.
        :param coords_filename (str):
            Name of input coordinates file
        :param constraints (Dict):
            Dictionary of common editable parameters for .constrains file.
            {"atoms": [List of 1-indexed atoms to fix], "force_constant":
            float]
        """
        self.molecule = molecule
        self.coords_filename = coords_filename
        self.constraints = constraints

    def write_input_files(self):
        self.molecule.to(filename=self.coords_filename)
        if self.constraints:
            constrains_string = self.constrains_template(
                molecule=self.molecule, reference_fnm=self.coords_filename,
                constraints=self.constraints)
            with open(".constrains", "w") as f:
                f.write(constrains_string)

    @staticmethod
    def constrains_template(molecule, reference_fnm, constraints) -> str:
        atoms_to_constrain = constraints["atoms"]
        force_constant = constraints["force_constant"]
        reference_fnm = reference_fnm
        mol = molecule
        atoms_for_mtd = [
            i
            for i in range(1, len(mol.sites) + 1)
            if i not in atoms_to_constrain
        ]
        # Write as 1-3,5 instead of 1,2,3,5
        interval_list = [atoms_for_mtd[0]]
        for i, v in enumerate(atoms_for_mtd):
            if v + 1 not in atoms_for_mtd:
                interval_list.append(v)
                if i != len(atoms_for_mtd) - 1:
                    interval_list.append(atoms_for_mtd[i + 1])
        force_constant = force_constant
        allowed_mtd_string = ",".join(
            [
                "{}-{}".format(interval_list[i], interval_list[i + 1])
                for i in range(len(interval_list))
                if i % 2 == 0
            ]
        )
        constrains_file_string = (
            "$constrain\n"
            + "  atoms: {}\n".format(
                ",".join([str(i) for i in atoms_to_constrain])
            )
            + "  force constant={}\n".format(force_constant)
            + "  reference={}\n".format(reference_fnm)
            + "$metadyn\n"
            + "  atoms: {}\n".format(allowed_mtd_string)
            + "$end"
        )

        return constrains_file_string
