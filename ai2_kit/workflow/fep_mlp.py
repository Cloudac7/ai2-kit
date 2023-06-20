from ai2_kit.core.executor import BaseExecutorConfig
from ai2_kit.core.artifact import ArtifactMap
from ai2_kit.core.log import get_logger
from ai2_kit.core.util import load_yaml_files
from ai2_kit.core.resource_manager import ResourceManager
from ai2_kit.domain import (
    deepmd,
    lammps,
    selector,
    cp2k,
    constant as const,
    updater,
    cll,
)

from pydantic import BaseModel
from typing import Dict, List, Optional, Any
from fire import Fire

import copy
import itertools
import os

logger = get_logger(__name__)


class FepExecutorConfig(BaseExecutorConfig):
    class Context(BaseModel):

        deepmd: deepmd.GenericDeepmdContextConfig
        lammps: lammps.GenericLammpsContextConfig
        cp2k: cp2k.GenericCp2kContextConfig

    context: Context


class WorkflowConfig(BaseModel):
    class General(BaseModel):
        type_map: List[str]
        mass_map: List[float]
        max_iters: int = 10

    class Branch(BaseModel):
        deepmd: deepmd.GenericDeepmdInputConfig
        cp2k: cp2k.GenericCp2kInputConfig
        threshold: selector.ThresholdSelectorInputConfig

    class Update(BaseModel):
        walkthrough: updater.WalkthroughUpdaterInputConfig

    general: General
    neu: Branch
    red: Branch
    lammps: lammps.GenericLammpsInputConfig
    update: Update


class FepWorkflowConfig(BaseModel):
    executors: Dict[str, FepExecutorConfig]
    artifacts: ArtifactMap
    workflow: Any

def fep_train_mlp(*config_files, executor: Optional[str] = None, path_prefix: Optional[str] = None):
    """
    Training ML potential for FEP
    """

    config_data = load_yaml_files(*config_files)
    config = FepWorkflowConfig.parse_obj(config_data)

    if executor not in config.executors:
        raise ValueError(f'executor {executor} is not found')
    if path_prefix is None:
        raise ValueError('path_prefix should not be empty')

    resource_manager = ResourceManager(
        executor_configs=config.executors,
        artifacts=config.artifacts,
        default_executor=executor,
    )

    context_config = config.executors[executor].context
    raw_workflow_config = copy.deepcopy(config.workflow)

    # output of each step
    neu_label_output: Optional[cll.ICllLabelOutput] = None
    red_label_output: Optional[cll.ICllLabelOutput] = None

    neu_selector_output: Optional[cll.ICllSelectorOutput] = None
    red_selector_output: Optional[cll.ICllSelectorOutput] = None

    neu_train_output: Optional[cll.ICllTrainOutput] = None
    red_train_output: Optional[cll.ICllTrainOutput] = None

    explore_output: Optional[cll.ICllExploreOutput] = None

    # cursor of update table
    update_cursor = 0
    # Start iteration
    for i in itertools.count(0):

        # parse workflow config
        workflow_config = WorkflowConfig.parse_obj(raw_workflow_config)
        if i >= workflow_config.general.max_iters:
            logger.info(f'Iteration {i} exceeds max_iters, stop iteration.')
            break

        # shortcut for type_map and mass_map
        type_map = workflow_config.general.type_map
        mass_map = workflow_config.general.mass_map

        # decide path prefix for each iteration
        iter_path_prefix = os.path.join(path_prefix, f'iters-{i:03d}')

        # label: cp2k
        red_cp2k_input = cp2k.GenericCp2kInput(
            config=workflow_config.red.cp2k,
            type_map=type_map,
            system_files=[] if red_selector_output is None else red_selector_output.get_model_devi_dataset(),
            initiated= i > 0,
        )
        red_cpk2_context = cp2k.GenericCp2kContext(
            config=context_config.cp2k,
            path_prefix=os.path.join(iter_path_prefix, 'red-label-cp2k'),
            resource_manager=resource_manager,
        )

        neu_cp2k_input = cp2k.GenericCp2kInput(
            config=workflow_config.neu.cp2k,
            type_map=type_map,
            system_files=[] if neu_selector_output is None else neu_selector_output.get_model_devi_dataset(),
            initiated= i > 0,
        )
        neu_cp2k_context = cp2k.GenericCp2kContext(
            config=context_config.cp2k,
            path_prefix=os.path.join(iter_path_prefix, 'neu-label-cp2k'),
            resource_manager=resource_manager,
        )


        red_label_output_future = cp2k.generic_cp2k(red_cp2k_input, red_cpk2_context)
        neu_label_output_future = cp2k.generic_cp2k(neu_cp2k_input, neu_cp2k_context)

        red_label_output = red_label_output_future.result()
        neu_label_output = neu_label_output_future.result()

        # Train
        red_deepmd_input = deepmd.GenericDeepmdInput(
            config=workflow_config.red.deepmd,
            type_map=type_map,
            old_dataset=[] if red_train_output is None else red_train_output.get_training_dataset(),
            new_dataset=red_label_output.get_labeled_system_dataset(),
            initiated= i > 0,
        )
        red_deepmd_context = deepmd.GenericDeepmdContext(
            path_prefix=os.path.join(iter_path_prefix, 'red-train-deepmd'),
            config=context_config.deepmd,
            resource_manager=resource_manager,
        )

        neu_deepmd_input = deepmd.GenericDeepmdInput(
            config=workflow_config.neu.deepmd,
            type_map=type_map,
            old_dataset=[] if neu_train_output is None else neu_train_output.get_training_dataset(),
            new_dataset=neu_label_output.get_labeled_system_dataset(),
            initiated= i > 0,
        )
        neu_deepmd_context = deepmd.GenericDeepmdContext(
            path_prefix=os.path.join(iter_path_prefix, 'neu-train-deepmd'),
            config=context_config.deepmd,
            resource_manager=resource_manager,
        )

        red_train_output_future = deepmd.generic_deepmd(red_deepmd_input, red_deepmd_context)
        neu_train_output_future = deepmd.generic_deepmd(neu_deepmd_input, neu_deepmd_context)

        red_train_output = red_train_output_future.result()
        neu_train_output = neu_train_output_future.result()

        # explore
        lammps_input = lammps.GenericLammpsInput(
            config=workflow_config.lammps,
            type_map=type_map,
            mass_map=mass_map,
            fep_options=lammps.GenericLammpsInput.FepOptions(
                neu_models=neu_train_output.get_mlp_models(),
                red_models=red_train_output.get_mlp_models(),
            ),
        )
        lammps_context = lammps.GenericLammpsContext(
            path_prefix=os.path.join(iter_path_prefix, 'explore-lammps'),
            config=context_config.lammps,
            resource_manager=resource_manager,
        )
        explore_output = lammps.generic_lammps(lammps_input, lammps_context).result()


        # select
        red_selector_input = selector.ThresholdSelectorInput(
            config=workflow_config.red.threshold,
            model_devi_data=explore_output.get_model_devi_dataset(),
            model_devi_out_filename=const.MODEL_DEVI_RED_OUT,
        )
        red_selector_context = selector.ThresholdSelectorContext(
            path_prefix=os.path.join(iter_path_prefix, 'red-selector-threshold'),
            resource_manager=resource_manager,
        )

        neu_selector_input = selector.ThresholdSelectorInput(
            config=workflow_config.neu.threshold,
            model_devi_data=explore_output.get_model_devi_dataset(),
            model_devi_out_filename=const.MODEL_DEVI_NEU_OUT,
        )
        neu_selector_context = selector.ThresholdSelectorContext(
            path_prefix=os.path.join(iter_path_prefix, 'neu-selector-threshold'),
            resource_manager=resource_manager,
        )

        red_selector_output_future = selector.threshold_selector(red_selector_input, red_selector_context)
        neu_selector_output_future = selector.threshold_selector(neu_selector_input, neu_selector_context)

        red_selector_output = red_selector_output_future.result()
        neu_selector_output = neu_selector_output_future.result()


        # Update
        update_config = workflow_config.update.walkthrough

        # nothing to update because the table is empty
        if not update_config.table:
            continue
        # keep using the latest config when it reach the end of table
        if update_cursor >= len(update_config.table):
            continue
        # update config
        update_cursor += 1


if __name__ == '__main__':
    # use python-fire to parse command line arguments
    Fire(fep_train_mlp)