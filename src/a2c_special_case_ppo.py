import networkx as nx
from sb3_contrib import MaskablePPO
import wandb
from stable_baselines3 import A2C, PPO
from stable_baselines3.common.callbacks import EvalCallback
from sb3_contrib.common.maskable.callbacks import MaskableEvalCallback
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.vec_env import VecEnv
from torch import nn
from wandb.integration.sb3 import WandbCallback
from gym.utils.env_checker import check_env
import torch as th

import reader
from callbacks import PSNLoadCallback, HParamCallback, AcceptanceRatioByNSPRsCallback, SeenNSPRsCallback
from heuristic_layers import P2CLoadBalanceHeuristic
from policies.features_extractors import GCNsFeaturesExtractor
from policies.hadrl_policy import HADRLPolicy
from utils import make_env, create_HADRL_PSN_file, create_HEENSO_PSN_file
from wrappers import ResetWithRealisticLoad, ResetWithLoadMixed


if __name__ == '__main__':
    psn_path = "../PSNs/waxman_50_servers.graphml"
    psn = reader.read_psn(psn_path)

    # training environment
    n_tr_envs = 40
    tr_nsprs_per_ep = 1
    tr_load = 0.5
    tr_time_limit = False
    tr_max_ep_steps = 1000
    tr_reset_load_class = ResetWithLoadMixed
    # tr_reset_load_kwargs = dict(rand_load=True, rand_range=(0., 1.))
    tr_reset_load_kwargs = dict(load=dict(cpu=0.5, ram=0.5, bw=0.2))
    # tr_reset_load_kwargs = dict(cpu_load=tr_load)
    placement_state = True
    accumulate_reward = True
    discount_acc_rew = True
    dynamic_connectivity = False
    dynamic_connectivity_kwargs = dict(link_bw=10_000)
    dynamic_topology = True # si potrebbe sempre wrappare, tanto poi serve MaskedPPO, altrimenti è come non avere masking
    perc_avail_nodes = 0.7
    tr_env = make_vec_env(
        env_id=make_env,
        n_envs=n_tr_envs,
        env_kwargs=dict(
            psn_path=psn_path,
            base_env_kwargs=dict(
                accumulate_reward=accumulate_reward,
                discount_acc_rew=discount_acc_rew,
                perc_avail_nodes=perc_avail_nodes
            ),
            time_limit=tr_time_limit,
            time_limit_kwargs=dict(max_episode_steps=tr_max_ep_steps),
            hadrl_nsprs=True,
            hadrl_nsprs_kwargs=dict(
                nsprs_per_ep=tr_nsprs_per_ep,
                vnfs_per_nspr=5,
                load=tr_load,
                always_one=True
            ),
            reset_load_class=tr_reset_load_class,
            reset_load_kwargs=tr_reset_load_kwargs,
            placement_state=placement_state,
            dynamic_connectivity=dynamic_connectivity,
            dynamic_connectivity_kwargs=dynamic_connectivity_kwargs,
            dynamic_topology=dynamic_topology
        ),
        seed=12,
    )

    # evaluation environment
    n_eval_envs = 4
    eval_nsprs_per_ep = 1
    eval_load = 0.5
    eval_time_limit = False
    eval_max_ep_steps = 1000
    eval_reset_load_class = ResetWithLoadMixed
    eval_reset_load_kwargs = dict(load=dict(cpu=0.5, ram=0.5, bw=0.2))
    # eval_reset_load_kwargs = dict(cpu_load=eval_load)
    eval_env = make_vec_env(
        env_id=make_env,
        n_envs=n_eval_envs,
        env_kwargs=dict(
            psn_path=psn_path,
            base_env_kwargs=dict(
                accumulate_reward=accumulate_reward,
                discount_acc_rew=discount_acc_rew,
                perc_avail_nodes=perc_avail_nodes,
            ),
            time_limit=eval_time_limit,
            time_limit_kwargs=dict(max_episode_steps=eval_max_ep_steps),
            reset_load_class=eval_reset_load_class,
            reset_load_kwargs=eval_reset_load_kwargs,
            hadrl_nsprs=True,
            hadrl_nsprs_kwargs=dict(
                nsprs_per_ep=eval_nsprs_per_ep,
                vnfs_per_nspr=5,
                load=eval_load,
                always_one=True
            ),
            placement_state=placement_state,
            dynamic_connectivity=dynamic_connectivity,
            dynamic_connectivity_kwargs=dynamic_connectivity_kwargs,
            dynamic_topology=dynamic_topology
        ),
        seed=12,
    )

    # model definition
    use_heuristic = False
    heu_kwargs = {'n_servers_to_sample': 4, 'heu_class': P2CLoadBalanceHeuristic,
                  'eta': 0.05, 'xi': 0.7, 'beta': 1.}
    policy = HADRLPolicy
    a2c_policy_kwargs = dict(psn=psn,
                         net_arch=dict(pi=[256, 128], vf=[256, 128, 32]),
                         activation_fn=nn.Tanh,
                         servers_map_idx_id=tr_env.get_attr('servers_map_idx_id', 0)[0],
                         gcn_layers_dims=(20, 20, 20),
                         use_heuristic=use_heuristic,
                         heu_kwargs=heu_kwargs, )
    ppo_policy_kwargs = dict(psn=psn,
                         net_arch=dict(pi=[256, 128], vf=[256, 128, 32]),
                         activation_fn=nn.Tanh,
                         servers_map_idx_id=tr_env.get_attr('servers_map_idx_id', 0)[0],
                         gcn_layers_dims=(20, 20, 20),
                         use_heuristic=use_heuristic,
                         heu_kwargs=heu_kwargs,
                         optimizer_class=th.optim.RMSprop,
                            optimizer_kwargs=dict(
                                alpha=0.99, eps=1e-5, weight_decay=0,
                            ),
                        )

    # a2c = A2C(policy=policy, env=tr_env, verbose=2, device='cuda:0',
    #             learning_rate=0.0001,
    #             n_steps=1,  # ogni quanti step fare un update
    #             gamma=0.99,
    #             gae_lambda=1.,
    #             ent_coef=0.01,
    #             seed=12,
    #             # max_grad_norm=0.9,
    #             use_rms_prop=True,
    #             tensorboard_log="../tb_logs/",
    #             policy_kwargs=a2c_policy_kwargs)
    
    # ppo = PPO(policy=policy, env=tr_env, verbose=2, device='cuda:1',
    #     policy_kwargs=ppo_policy_kwargs,
    #     learning_rate=0.0001,
    #     n_steps=1,
    #     gae_lambda=1.,
    #     n_epochs=1,
    #     batch_size=20,  # n_steps * n_envs
    #     normalize_advantage=False,
    #     clip_range_vf=None,
    #     tensorboard_log="../tb_logs/",
    #     seed=12,
    # )

    maskable_ppo = MaskablePPO(policy='MultiInputPolicy', env=tr_env, verbose=2, device='cuda:0',
        # policy_kwargs=ppo_policy_kwargs,
        policy_kwargs=dict(
            activation_fn=nn.Tanh,
            net_arch=dict(pi=[256, 128], vf=[256, 128, 32]),
            features_extractor_class=GCNsFeaturesExtractor,
            share_features_extractor=False,
            features_extractor_kwargs=dict(
                psn=psn,
                activation_fn=nn.Tanh,
                gcn_layers_dims=ppo_policy_kwargs['gcn_layers_dims'],
            )
        ),
        learning_rate=0.0001,
        n_steps=1,
        gae_lambda=1.,
        n_epochs=1,
        batch_size=40,  # n_steps * n_envs
        normalize_advantage=False,
        clip_range_vf=None,
        tensorboard_log="../tb_logs/",
        seed=12,)

    # define some training hyperparams
    tot_tr_steps = 100_000_000

    if tr_reset_load_class is not None:
        tr_load = tr_reset_load_kwargs.get('cpu_load', None)

    # wandb stuff
    config = {
        "policy name": policy.name,
        "total tr timesteps": tot_tr_steps,
        "n tr envs": n_tr_envs,
        "n eval envs": n_eval_envs,
        "NSPRs per training ep": tr_nsprs_per_ep,
        "max steps per tr ep": tr_max_ep_steps if tr_time_limit else None,
        "PSN load (tr)": tr_load,
        "NSPRs per eval ep": eval_nsprs_per_ep,
        "max steps per eval ep": eval_max_ep_steps if eval_time_limit else None,
        "PSN load (eval)": eval_load,
        "GCNs layers dims": a2c_policy_kwargs['gcn_layers_dims'],
        "mpl_extractor arch": a2c_policy_kwargs["net_arch"],
        "use placement state": placement_state,
        "accumulate reward": accumulate_reward,
        "discount acceptance reward": discount_acc_rew,
        "dynamic connectivity": dynamic_connectivity,
        "dynamic load range": "0-0.9",
        "dynamic topology": dynamic_topology,
        "percentage of available nodes": perc_avail_nodes,
        "use heuristic": use_heuristic,
        **heu_kwargs,
    }

    wandb_run = wandb.init(
        project="Masked actions",
        dir="../",
        name="Maskable PPO actual removal (same act (tanh), wax 50, load 0.5, 0.7 avail nodes) 100M steps, 40 envs",
        config=config,
        sync_tensorboard=True,  # auto-upload sb3's tensorboard metrics
        save_code=True,  # optional
    )

    # training callbacks
    list_of_callbacks = [
        # AcceptanceRatioByStepsCallback(env=tr_env, name="Acceptance ratio (by steps)",
        #                                steps_per_tr_phase=500, verbose=2),

        AcceptanceRatioByNSPRsCallback(env=tr_env, name="Train acceptance ratio (by NSPRs)",
                                       nsprs_per_tr_phase=1000, verbose=2),

        HParamCallback(tr_env.num_envs, 1, tr_nsprs_per_ep,
                       tr_load,
                       tr_max_ep_steps=tr_max_ep_steps if tr_time_limit else None,
                       eval_nsprs_per_ep=1,
                       eval_psn_load=1,
                       eval_max_ep_steps=1 if False else None,
                       use_placement_state=placement_state,
                       use_heuristic=use_heuristic, heu_kwargs=heu_kwargs, ),

        # WandbCallback(model_save_path=f"../models/{wandb_run.id}",
        #               verbose=2,
        #               model_save_freq=10_000),
        
        # EvalCallback(eval_env=eval_env, n_eval_episodes=1000, warn=True,
        #              eval_freq=1, deterministic=True, verbose=2,
        #              callback_after_eval=AcceptanceRatioByNSPRsCallback(
        #                  env=eval_env,
        #                  name="Eval acceptance ratio (by NSPRs)",
        #                  nsprs_per_tr_phase=1,  # must be 1 for eval (default value)
        #                  verbose=2
        #              )),
        
        MaskableEvalCallback(eval_env=eval_env, n_eval_episodes=1000, warn=True,
                            eval_freq=5000, deterministic=True, verbose=2,
                            callback_after_eval=AcceptanceRatioByNSPRsCallback(
                                env=eval_env,
                                name="Eval acceptance ratio (by NSPRs)",
                                nsprs_per_tr_phase=1,  # must be 1 for eval (default value)
                                verbose=2
                            )),

        PSNLoadCallback(env=tr_env, freq=500, verbose=1),

        SeenNSPRsCallback(env=tr_env, freq=100, verbose=1),
    ]

    # A2C training
    # a2c.learn(total_timesteps=tot_tr_steps,
    #             log_interval=10,
    #             callback=list_of_callbacks)

    # wandb_run.finish()

    # # PPO training
    # ppo.learn(total_timesteps=tot_tr_steps,
    #             log_interval=10,
    #             callback=list_of_callbacks)

    # Maskable PPO training
    maskable_ppo.learn(total_timesteps=tot_tr_steps,
                log_interval=10,
                callback=list_of_callbacks)

    wandb_run.finish()