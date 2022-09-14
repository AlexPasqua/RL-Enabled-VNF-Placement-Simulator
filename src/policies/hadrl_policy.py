from typing import Callable, Dict, List, Optional, Type, Union, Tuple

import gym
import networkx as nx
import torch as th
from stable_baselines3.common.policies import MultiInputActorCriticPolicy
from stable_baselines3.common.preprocessing import preprocess_obs
from torch import nn

from .features_extractors import HADRLFeaturesExtractor
from .mlp_extractors.hadrl_mlp_extractor import HADRLActorCriticNet


class HADRLPolicy(MultiInputActorCriticPolicy):
    def __init__(
            self,
            observation_space: gym.spaces.Space,
            action_space: gym.spaces.Space,
            lr_schedule: Callable[[float], float],
            psn: nx.Graph,
            net_arch: Optional[List[Union[int, Dict[str, List[int]]]]] = None,
            activation_fn: Type[nn.Module] = nn.Tanh,
            gcn_out_channels: int = 60,
            nspr_out_features: int = 4,
            *args,
            **kwargs,
    ):
        self.psn = psn
        self.gcn_out_channels = gcn_out_channels
        self.nspr_out_features = nspr_out_features

        super(HADRLPolicy, self).__init__(
            observation_space,
            action_space,
            lr_schedule,
            net_arch,
            activation_fn,
            # Pass remaining arguments to base class
            *args,
            **kwargs,
        )

        # non-shared features extractors for the actor and the critic
        self.policy_features_extractor = HADRLFeaturesExtractor(
            observation_space, psn, th.tanh, gcn_out_channels,
            nspr_out_features
        )
        self.value_features_extractor = HADRLFeaturesExtractor(
            observation_space, psn, th.relu, gcn_out_channels,
            nspr_out_features
        )
        delattr(self, "features_extractor")  # remove the shared features extractor

        # TODO: check what this step actually does
        # Disable orthogonal initialization
        self.ortho_init = False

    def _build_mlp_extractor(self) -> None:
        self.mlp_extractor = HADRLActorCriticNet(
            self.observation_space, self.psn, self.features_dim,
            self.gcn_out_channels, self.nspr_out_features
        )

    def extract_features(self, obs: th.Tensor) -> Tuple[th.Tensor, th.Tensor]:
        """
        Preprocess the observation if needed and extract features.

        :param obs: Observation
        :return: the output of the feature extractor(s)
        """
        assert self.policy_features_extractor is not None and \
               self.value_features_extractor is not None
        preprocessed_obs = preprocess_obs(obs, self.observation_space,
                                          normalize_images=self.normalize_images)
        policy_features = self.policy_features_extractor(preprocessed_obs)
        value_features = self.value_features_extractor(preprocessed_obs)
        return policy_features, value_features

    def forward(self, obs: th.Tensor, deterministic: bool = False) -> Tuple[th.Tensor, th.Tensor, th.Tensor]:
        """
        Forward pass in all the networks (actor and critic)

        :param obs: Observation
        :param deterministic: Whether to sample or use deterministic actions
        :return: action, value and log probability of the action
        """
        # Preprocess the observation if needed
        policy_features, value_features = self.extract_features(obs)
        latent_pi = self.mlp_extractor.forward_actor(policy_features)
        latent_vf = self.mlp_extractor.forward_critic(value_features)

        # Evaluate the values for the given observations
        values = self.value_net(latent_vf)
        distribution = self._get_action_dist_from_latent(latent_pi)
        actions = distribution.get_actions(deterministic=deterministic)
        log_prob = distribution.log_prob(actions)
        return actions, values, log_prob

    def evaluate_actions(self, obs: th.Tensor, actions: th.Tensor) -> Tuple[th.Tensor, th.Tensor, th.Tensor]:
        """
        Evaluate actions according to the current policy,
        given the observations.

        :param obs: Observation
        :param actions: Actions
        :return: estimated value, log likelihood of taking those actions
            and entropy of the action distribution.
        """
        # Preprocess the observation if needed
        policy_features, value_features = self.extract_features(obs)
        latent_pi = self.mlp_extractor.forward_actor(policy_features)
        latent_vf = self.mlp_extractor.forward_critic(value_features)
        distribution = self._get_action_dist_from_latent(latent_pi)
        log_prob = distribution.log_prob(actions)
        values = self.value_net(latent_vf)
        return values, log_prob, distribution.entropy()

    def predict_values(self, obs: th.Tensor) -> th.Tensor:
        """
        Get the estimated values according to the current policy given the observations.

        :param obs: Observation
        :return: the estimated values.
        """
        _, value_features = self.extract_features(obs)
        latent_vf = self.mlp_extractor.forward_critic(value_features)
        return self.value_net(latent_vf)
