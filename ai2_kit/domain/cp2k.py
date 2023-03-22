from ai2_kit.core.artifact import Artifact
from ai2_kit.core.script import BashScript, BashStep, BashTemplate
from ai2_kit.core.job import GatherJobsFuture, retry_fn

from ai2_kit.core.future import DummyFuture, IFuture, map_future

from ai2_kit.core.util import merge_dict, parse_cp2k_input
from ai2_kit.core.log import get_logger

from typing import List, Union
from pydantic import BaseModel
from dataclasses import dataclass

import copy
import os

from .data_helper import LammpsOutputHelper, XyzHelper, Cp2kOutputHelper, ase_atoms_to_cp2k_input_data
from .cll import ICllLabelInput, ICllLabelOutput, BaseCllContext

logger = get_logger(__name__)

class GenericCp2kInputConfig(BaseModel):
    init_system_files: List[str] = []
    limit: int = 50
    input_template: Union[dict, str]
    """
    Input template for cp2k. Could be a dict or content of a cp2k input file.

    Note:
    If you are using files in input templates, it is recommended to use artifact name instead of literal path.
    String starts with '@' will be treated as artifact name.
    For examples, FORCE_EVAL/DFT/BASIS_SET_FILE_NAME = @cp2k/basic_set.
    You can still use literal path, but it is not recommended.
    """

class GenericCp2kContextConfig(BaseModel):
    script_template: BashTemplate
    cp2k_cmd: str = 'cp2k'
    concurrency: int = 5

@dataclass
class GenericCp2kInput(ICllLabelInput):

    config: GenericCp2kInputConfig
    system_files: List[Artifact]
    type_map: List[str]
    initiated: bool = False

    def set_systems(self, systems: List[Artifact]):
        self.system_files = systems


@dataclass
class GenericCp2kContext(BaseCllContext):
    config: GenericCp2kContextConfig


@dataclass
class GenericCp2kOutput(ICllLabelOutput):
    cp2k_outputs: List[Artifact]

    def get_labeled_system_dataset(self):
        return self.cp2k_outputs


def generic_cp2k(input: GenericCp2kInput, ctx: GenericCp2kContext) -> IFuture[GenericCp2kOutput]:

    executor = ctx.resource_manager.default_executor

    # For the first round
    if not input.initiated:
        input.system_files += ctx.resource_manager.get_artifacts(input.config.init_system_files)

    # setup workspace
    work_dir = os.path.join(executor.work_dir, ctx.path_prefix)
    [tasks_dir] = executor.setup_workspace(work_dir, ['tasks'])

    # prepare input template
    if isinstance(input.config.input_template, str):
        input_template = parse_cp2k_input(input.config.input_template)
    else:
        input_template = copy.deepcopy(input.config.input_template)

    # resolve artifacts resources in the input template
    basic_set_file: str = input_template['FORCE_EVAL']['DFT']['BASIS_SET_FILE_NAME']
    if basic_set_file.startswith('@'):
        logger.info(f'resolve artifact {basic_set_file}')
        input_template['FORCE_EVAL']['DFT']['BASIS_SET_FILE_NAME'] = \
            ctx.resource_manager.resolve_artifact(basic_set_file[1:])[0].url

    potential_file: str = input_template['FORCE_EVAL']['DFT']['POTENTIAL_FILE_NAME']
    if potential_file.startswith('@'):
        logger.info(f'resolve artifact {potential_file}')
        input_template['FORCE_EVAL']['DFT']['POTENTIAL_FILE_NAME'] = \
            ctx.resource_manager.resolve_artifact(potential_file[1:])[0].url

    # resolve data files
    lammps_dump_files: List[Artifact] = []
    xyz_files: List[Artifact] = []

    # TODO: support POSCAR in the future
    # TODO: refactor the way of handling different file formats
    for system_file in input.system_files:
        if LammpsOutputHelper.is_match(system_file):
            lammps_out = LammpsOutputHelper(system_file)
            lammps_dump_files.extend(lammps_out.get_passed_dump_files())
        elif XyzHelper.is_match(system_file):
            xyz_files.append(system_file)
        else:
            raise ValueError(f'unsupported format {system_file.url}: {system_file.format}')

    # create task dirs and prepare input files
    cp2k_task_dirs = []
    if lammps_dump_files or xyz_files:
        cp2k_task_dirs = executor.run_python_fn(make_cp2k_task_dirs)(
            lammps_dump_files=[a.url for a in lammps_dump_files],
            xyz_files=[a.url for a in xyz_files],
            type_map=input.type_map,
            base_dir=tasks_dir,
            input_template=input_template,
            limit=input.config.limit,
        )
    else:
        logger.warn('no available candidates, skip')
        return DummyFuture(GenericCp2kOutput(cp2k_outputs=[]))

    # group cp2k tasks by concurrency
    concurrency = ctx.config.concurrency
    steps_group = [list() for _ in range(concurrency)]
    for i, cp2k_task_dir in enumerate(cp2k_task_dirs):
        steps = steps_group[i % concurrency]
        step = BashStep(
            cwd=cp2k_task_dir,
            cmd=[ctx.config.cp2k_cmd, '-i input.inp 1>> output 2>> output'],
            checkpoint='cp2k',
        )
        steps.append(step)

    # run tasks
    jobs = []
    for steps in steps_group:
        if not steps:
            continue
        script = BashScript(
            template=ctx.config.script_template,
            steps=steps,
        )
        job = executor.submit(script.render(), cwd=tasks_dir)
        jobs.append(job)

    future = GatherJobsFuture(jobs, done_fn=retry_fn(max_tries=2), raise_exception=True)

    cp2k_outputs = [Artifact.of(
        url=url,
        format=Cp2kOutputHelper.format,
        executor=executor.name,
        attrs=dict(),  # TODO: success from input
    ) for url in cp2k_task_dirs]

    return map_future(future, GenericCp2kOutput(cp2k_outputs=cp2k_outputs))


def __make_cp2k_task_dirs():
    def make_cp2k_task_dirs(lammps_dump_files: List[str],
                            xyz_files: List[str],
                            type_map: List[str],
                            input_template: dict,
                            base_dir: str,
                            limit: int = 0,
                            input_file_name: str = 'input.inp',
                            ) -> List[str]:
        """Generate CP2K input files from LAMMPS dump files or XYZ files."""

        # TODO: pymatgen has a better support for cp2k input, replace cp2k_input_tools with pymatgen in the future
        # https://pymatgen.org/pymatgen.io.cp2k.inputs.html#pymatgen.io.cp2k.inputs.Cp2kInput
        from cp2k_input_tools import DEFAULT_CP2K_INPUT_XML
        from cp2k_input_tools.generator import CP2KInputGenerator

        import ase.io
        from ase import Atoms

        cp2k_generator = CP2KInputGenerator(DEFAULT_CP2K_INPUT_XML)
        task_dirs = []
        atoms_list: List[Atoms] = []

        # read atoms
        for dump_file in lammps_dump_files:
            atoms_list += ase.io.read(dump_file, ':', format='lammps-dump-text', order=False, specorder=type_map)  # type: ignore
        for xyz_file in xyz_files:
            atoms_list += ase.io.read(xyz_file, ':', format='extxyz', order=False)  # type: ignore

        if limit > 0:
            atoms_list = atoms_list[:limit]

        for i, atoms in enumerate(atoms_list):
            # create task dir
            task_dir = os.path.join(base_dir, f'{str(i).zfill(6)}')
            os.makedirs(task_dir, exist_ok=True)

            # create input file
            input_data = copy.deepcopy(input_template)
            coords, cell = ase_atoms_to_cp2k_input_data(atoms)
            merge_dict(input_data, {
                'FORCE_EVAL': {
                    'SUBSYS': {
                        'COORD': {
                            '*': coords
                        },
                        'CELL': {
                            'A': cell[0],
                            'B': cell[1],
                            'C': cell[2],
                        }
                    }
                }
            })
            input_text = '\n'.join(cp2k_generator.line_iter(input_data))
            with open(os.path.join(task_dir, input_file_name), 'w') as f:
                f.write(input_text)
            task_dirs.append(task_dir)
        return task_dirs

    return make_cp2k_task_dirs
make_cp2k_task_dirs = __make_cp2k_task_dirs()