from __future__ import annotations

from dataclasses import dataclass

from .common import TypeProtocol, TypeProtocolT
@dataclass
class Resolver:
    module_name: str
    types: dict[str, TypeProtocol]
    imports: dict[str, Resolver]
    touched_imports: set[str]

    def get_local(self, name: str) -> TypeProtocol:
        return self.types[name]

    def get_imported(self, module_name: str, name: str) -> TypeProtocol:
        resolver = self.imports[module_name]
        typ = resolver.get_local(name)
        prefixed = typ.with_module_prefix(f'{module_name}.')
        if prefixed is not typ:
            self.touched_imports.add(module_name)
        return prefixed

    def get(self, name: str) -> TypeProtocol:
        if ':' in name:
            module_name, type_name = name.split(':', 1)
            if module_name == self.module_name:
                return self.get_local(type_name)
            return self.get_imported(module_name, type_name)

        try:
            return self.types[name]
        except KeyError:
            pass

        for module_name, resolver in self.imports.items():
            try:
                return self.get_imported(module_name, name)
            except KeyError:
                continue

        raise KeyError(name)

    def set(self, name: str, typ: TypeProtocolT) -> TypeProtocolT:
        self.types[name] = typ
        return typ
