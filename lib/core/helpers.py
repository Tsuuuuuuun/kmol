import datetime
import hashlib
import json
import logging
import os
import timeit
from typing import Type, Any, Dict, Union, T, Optional

import humps
import torch

import importlib
from lib.core.exceptions import ReflectionError


class Timer:

    def __init__(self):
        self.start_time = None
        self.reset()

    def __call__(self) -> float:
        return timeit.default_timer() - self.start_time

    def __str__(self) -> str:
        return str(datetime.timedelta(seconds=round(self(), 0)))

    def reset(self) -> None:
        self.start_time = timeit.default_timer()


class SuperFactory:

    @staticmethod
    def find_descendants(parent: Type[T]) -> Dict[str, Type[T]]:
        descendants = {}

        for child in parent.__subclasses__():
            descendants[child.__name__] = child

            if len(child.__subclasses__()) > 0:
                descendants = {**descendants, **SuperFactory.find_descendants(child)}

        return descendants

    @staticmethod
    def create(
            instantiator: Optional[Type[Any]],
            dynamic_parameters: Dict[str, Any],
            loaded_parameters: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        The super factory is a mix between an abstract factory and a dependency injector.
        If an abstract class is requested, we check all child classes which extend that abstract class
        and select the one specified by the "type" option. We then proceed to set all other attributes
        based on the "option_values". If one of the attributes is expected to be another object, it will
        be created in a recursive manner. The typing of the constructor is important for dependency injection to work!

        :type instantiator: The desired class, or its abstraction. Can be "None" when using reflections (see below).
        :type loaded_parameters: Additional options which are already loaded. They just get appended to the dynamic ones
        :type dynamic_parameters: A list of options which will be injected recursively. Can include a "type" option.
            if "type" is of format "lib.package.subpackage.ObjectName" it will be reflected directly.
            if "type" is a string in "snake_case" format, a matching descendant from "instantiator" will be searched for
            ie: requesting a "very_smart" object descendant of "AbstractCalculator" will fetch the "VerySmartCalculator"
        """

        logging.debug("Super Factory --- Instantiator --- {}".format(instantiator))
        logging.debug("Super Factory --- Dynamic Parameters --- {}".format(dynamic_parameters))
        logging.debug("Super Factory --- Loaded Parameters --- {}".format(loaded_parameters))
        logging.debug("------------------------------------------------------------")

        dynamic_parameters = dynamic_parameters.copy()
        if "type" in dynamic_parameters:

            dependency_type = dynamic_parameters.pop("type")

            if "." in dependency_type:
                instantiator = SuperFactory.reflect(dependency_type)
            else:
                if type(instantiator) is type(Union) and type(None) in instantiator.__args__:
                    # Fix for Optional arguments
                    instantiator = instantiator.__args__[0]

                option_key = instantiator.__name__.replace("Abstract", "")
                dependency_name = "{}_{}".format(dependency_type, option_key)
                dependency_name = humps.pascalize(dependency_name)

                subclasses = SuperFactory.find_descendants(instantiator)
                if dependency_name not in subclasses:
                    raise ReflectionError("Dependency not found: {}. Available options are: {}".format(
                        dependency_name, subclasses.keys())
                    )

                instantiator = subclasses.get(dependency_name)

        if len(dynamic_parameters) > 0:
            parameters = instantiator.__init__.__code__.co_varnames
            attributes = instantiator.__init__.__annotations__

            for option_name, option_value in dynamic_parameters.items():
                if option_name not in parameters:
                    raise ReflectionError("Unknown option for [{}] ---> [{}]".format(
                        instantiator.__name__, option_name)
                    )

                if option_name not in attributes:
                    continue  # for 3rd party libraries that don't use type hints...

                if (
                        type(option_value) is dict
                        and not (hasattr(attributes[option_name], "_name") and attributes[option_name]._name == "Dict")
                ):
                    # if the option is a dictionary, and the argument is not expected to be one
                    # we consider it an additional object which we instantiate/inject recursively
                    dynamic_parameters[option_name] = SuperFactory.create(attributes[option_name], option_value)

        options = dynamic_parameters
        if loaded_parameters is not None:
            options = {**options, **loaded_parameters}

        return instantiator(**options)

    @staticmethod
    def reflect(dependency: str) -> Type[Any]:
        logging.debug("Reflecting --- {}".format(dependency))
        logging.debug("------------------------------------------------------------")

        module_name, class_name = dependency.rsplit(".", 1)
        module = importlib.import_module(module_name)

        return getattr(module, class_name)


class CacheManager:

    def __init__(self, cache_location: str):
        self._cache_location = cache_location

        if not os.path.exists(self._cache_location):
            os.makedirs(self._cache_location)

    def _sort(self, dictionary: Dict[str, Any]) -> Dict[str, Any]:
        for key, value in dictionary.items():
            if type(value) is dict:
                dictionary[key] = self._sort(value)

        return dict(sorted(dictionary.items()))

    def key(self, **kwargs) -> str:
        options = self._sort(kwargs)
        options = json.dumps(options)

        return hashlib.md5(options.encode("utf-8")).hexdigest()

    def has(self, key: str) -> bool:
        return os.path.isfile("{}/{}".format(self._cache_location, key))

    def load(self, key: str) -> Any:
        return torch.load("{}/{}".format(self._cache_location, key))

    def save(self, data: Any, key: str) -> Any:
        return torch.save(data, "{}/{}".format(self._cache_location, key))

    def delete(self, key: str) -> None:
        try:
            os.remove("{}/{}".format(self._cache_location, key))
        except FileNotFoundError:
            pass
