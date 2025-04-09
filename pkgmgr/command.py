from abc import abstractmethod
import shlex
from typing import Optional, Tuple, Union, Callable, List
from dataclasses import dataclass, field
import inspect
import traceback


from pkgmgr.printer import aERROR_EXIT

from .aio import command_runner_stream, command_runner_stream_with_output
from .helpers import async_all

CommandResult = Tuple[bool, str, str]
CommandLike = Union[str, Callable[[], CommandResult]]


class Command:
    """
    A class that represents a command.
    """

    @abstractmethod
    async def run(self) -> bool:
        pass

    @abstractmethod
    async def run_with_output(self) -> CommandResult:
        pass

    def with_replacement_part(self, part: str) -> "Command":
        raise NotImplementedError(
            "This method is not implemented for this command type."
        )


class CompoundCommand(Command):
    """
    A class that represents a command.
    """

    def __init__(self, commands: List[Command]):
        self.commands = commands

    async def run(self) -> bool:
        return await async_all(await command.run() for command in self.commands)

    async def run_with_output(self) -> CommandResult:
        output_all, stderr_all = [], []
        ret_code = True
        for cmd in self.commands:
            ret_code, output, stderr = await cmd.run_with_output()
            output_all.append(output)
            stderr_all.append(stderr)
            if not ret_code:
                break
        return ret_code, "\n".join(output_all), "\n".join(stderr_all)

    def with_replacement_part(self, part: str) -> "Command":
        for command in self.commands:
            command.with_replacement_part(part)
        return self


class ShellScript(Command):
    """
    A class that represents a shell script.
    """

    def __init__(self, script: str, success_ret_code: Optional[set[int]] = None):
        self.script = script
        self.success_ret_code: set[int] = success_ret_code or {0}
        # self.piped_cmds: Optional[Command] = None
        self._modified_script: Optional[str] = None

    def get_script(self) -> str:
        if self._modified_script:
            return self._modified_script
        return self.script

    async def run(self) -> bool:
        """
        Pipe the command to another command.
        """
        ret_code = await command_runner_stream(shlex.split(self.get_script()))
        return self.check_ret_code(ret_code)

    async def run_with_output(self) -> CommandResult:
        """
        Pipe the command to another command.
        """
        ret_code, output, stderr = await command_runner_stream_with_output(
            shlex.split(self.get_script())
        )
        return self.check_ret_code(ret_code), output, stderr

    def check_ret_code(self, retcode: int) -> bool:
        """
        Check if the return code is in the success return code set.
        """
        return retcode in self.success_ret_code

    def with_replacement_part(self, part: str) -> "Command":
        if "{}" not in self.script:
            raise ValueError(
                "Script must contain '{}' placeholder for replacement part."
            )
        self._modified_script = self.script.replace("{}", part)
        return self


class FunctionCommand(Command):

    def __init__(self, functor: Callable[[], CommandResult]):
        self.functor = functor

    async def run(self) -> bool:
        return (await self.run_with_output())[0]

    async def run_with_output(self) -> CommandResult:
        try:
            if inspect.iscoroutinefunction(self.functor):
                return await self.functor()
            else:
                return self.functor()
        except Exception as e:

            aERROR_EXIT(
                f"Error while executing function {self.functor.__name__}: {traceback.format_exc()}"
            )
            raise e
