"""
Generic resources: the operations that all weclapp resources share.
"""

import builtins
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, ClassVar, Generic, Literal, TypeVar, overload

from weclapp_client._http import HttpTransport, QueryParams, entity_path
from weclapp_client.exceptions import AmbiguousResultError, InvalidQueryError, WeclappError
from weclapp_client.models.base import WeclappCreateModel, WeclappEntity, WeclappUpdateModel
from weclapp_client.query import Filter, validate_filters

EntityT = TypeVar("EntityT", bound=WeclappEntity)
CreateT = TypeVar("CreateT", bound=WeclappCreateModel)
UpdateT = TypeVar("UpdateT", bound=WeclappUpdateModel)

MAX_PAGE_SIZE = 1000
"""the maximum page size weclapp allows for most resources"""

_ALWAYS_LOADED = ("id", "version")


class ReadResource(Generic[EntityT]):
    """A resource that can be read: iterate, list, count, get and find_one."""

    path: ClassVar[str]
    """path of the resource relative to the base URL, e.g. ``user``"""
    known_properties: ClassVar[frozenset[str]]
    """all properties of the entity (camelCase); used to check ``properties`` and ``sort``"""
    filterable_properties: ClassVar[frozenset[str]]
    """properties that weclapp accepts in filters"""
    entity_model: type[EntityT]

    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    def iterate(
        self,
        *filters: Filter,
        properties: Sequence[str] | None = None,
        sort: str = "id",
        page_size: int = MAX_PAGE_SIZE,
    ) -> Iterator[EntityT]:
        """
        Iterates over all entities that match all filters, fetching one page after the other.

        :param properties: load only these properties (camelCase); ``id`` and ``version`` are always loaded
        :param sort: property to sort by, prefixed with ``-`` for descending order; several separated by commas
        :param page_size: entities per request, at most 1000
        :raises InvalidQueryError: if a filter, property or sort key is not supported by the resource
        """
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}, got {page_size}")
        params = self._query_params(filters, properties, sort)
        return self._pages(params, page_size)

    def list(
        self,
        *filters: Filter,
        properties: Sequence[str] | None = None,
        sort: str = "id",
        page_size: int = MAX_PAGE_SIZE,
    ) -> builtins.list[EntityT]:
        """Like :meth:`iterate`, but returns all matching entities as a list."""
        return builtins.list(self.iterate(*filters, properties=properties, sort=sort, page_size=page_size))

    def count(self, *filters: Filter) -> int:
        """Returns the number of entities that match all filters."""
        validate_filters(filters, self.filterable_properties, self.path)
        data = self._transport.request_json("GET", f"{self.path}/count", params=_filter_params(filters))
        result = data.get("result") if isinstance(data, dict) else None
        if not isinstance(result, int):
            raise WeclappError(f"weclapp returned an unexpected count response for {self.path}")
        return result

    def get(self, entity_id: str) -> EntityT:
        """
        Returns the entity with the given id.

        :raises NotFoundError: if there is no such entity
        """
        return self._parse(self._transport.request_json("GET", entity_path(self.path, entity_id)))

    def find_one(self, *filters: Filter, properties: Sequence[str] | None = None) -> EntityT | None:
        """
        Returns the only entity that matches all filters, or ``None`` if there is none.

        :raises AmbiguousResultError: if more than one entity matches
        """
        if not filters:
            raise InvalidQueryError("find_one needs at least one filter")
        params = [*self._query_params(filters, properties, "id"), ("page", "1"), ("pageSize", "2")]
        items = self._result_list(self._transport.request_json("GET", self.path, params=params))
        if len(items) > 1:
            raise AmbiguousResultError(f"More than one {self.path} matches the filters")
        return self._parse(items[0]) if items else None

    def _pages(self, params: QueryParams, page_size: int) -> Iterator[EntityT]:
        page = 1
        while True:
            page_params = [*params, ("page", str(page)), ("pageSize", str(page_size))]
            items = self._result_list(self._transport.request_json("GET", self.path, params=page_params))
            for item in items:
                yield self._parse(item)
            if len(items) < page_size:
                return
            page += 1

    def _query_params(self, filters: Sequence[Filter], properties: Sequence[str] | None, sort: str) -> QueryParams:
        validate_filters(filters, self.filterable_properties, self.path)
        params = _filter_params(filters)
        sort_keys = [key.strip() for key in sort.split(",") if key.strip()]
        for key in sort_keys:
            self._check_property(key.removeprefix("-"), "sort")
        if sort_keys:
            params.append(("sort", ",".join(sort_keys)))
        if properties is not None:
            for name in properties:
                self._check_property(name, "properties")
            selected = list(dict.fromkeys([*_ALWAYS_LOADED, *properties]))
            params.append(("properties", ",".join(selected)))
        return params

    def _check_property(self, name: str, usage: str) -> None:
        if name not in self.known_properties:
            raise InvalidQueryError(f"Unknown property {name!r} in {usage} of {self.path}")

    def _result_list(self, data: Any) -> builtins.list[Any]:
        result = data.get("result") if isinstance(data, dict) else None
        if not isinstance(result, builtins.list):
            raise WeclappError(f"weclapp returned an unexpected list response for {self.path}")
        return result

    def _parse(self, data: Any) -> EntityT:
        return self.entity_model.model_validate(data)


def _filter_params(filters: Sequence[Filter]) -> builtins.list[tuple[str, str]]:
    return [condition.to_query_param() for condition in filters]


def _dry_run_params(dry_run: bool) -> builtins.list[tuple[str, str]]:
    return [("dryRun", "true")] if dry_run else []


class WriteResource(ReadResource[EntityT], Generic[EntityT, CreateT, UpdateT]):
    """A resource whose entities can also be created and updated."""

    @overload
    def create(self, data: CreateT, *, dry_run: Literal[False] = False) -> EntityT: ...

    @overload
    def create(self, data: CreateT, *, dry_run: Literal[True]) -> None: ...

    @overload
    def create(self, data: CreateT, *, dry_run: bool) -> EntityT | None: ...

    def create(self, data: CreateT, *, dry_run: bool = False) -> EntityT | None:
        """
        Creates an entity and returns it as stored by weclapp.

        A ``POST`` is not retried if its outcome is unclear (e.g. after a read timeout), so look up whether the entity
        exists before creating it again.

        :param dry_run: let weclapp validate the data without storing it; returns ``None`` because weclapp does not
            assign ids in dry runs
        """
        result = self._transport.request_json(
            "POST", self.path, params=_dry_run_params(dry_run), json_body=data.to_payload()
        )
        return None if dry_run else self._parse(result)

    @overload
    def update(self, current: EntityT, changes: UpdateT, *, dry_run: Literal[False] = False) -> EntityT: ...

    @overload
    def update(self, current: EntityT, changes: UpdateT, *, dry_run: Literal[True]) -> None: ...

    @overload
    def update(self, current: EntityT, changes: UpdateT, *, dry_run: bool) -> EntityT | None: ...

    def update(self, current: EntityT, changes: UpdateT, *, dry_run: bool = False) -> EntityT | None:
        """
        Applies the changes to the entity (partial update) and returns the updated entity.

        ``id`` and ``version`` are taken from ``current``, so the update fails with :class:`OptimisticLockError` if the
        entity was changed in the meantime. If ``changes`` contains no field, no request is sent and ``current`` is
        returned.

        :param dry_run: let weclapp validate the changes without storing them; returns ``None``
        """
        payload: Mapping[str, Any] = changes.to_payload()
        if not payload:
            return None if dry_run else current
        result = self._transport.request_json(
            "PUT",
            entity_path(self.path, current.id),
            params=[("ignoreMissingProperties", "true"), *_dry_run_params(dry_run)],
            json_body={**payload, "version": current.version},
        )
        return None if dry_run else self._parse(result)
