import numbers
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import torch
import torch.nn.functional as F

from torch_geometric.data import Data, HeteroData
from torch_geometric.data.datapipes import functional_transform
from torch_geometric.data.storage import EdgeStorage, NodeStorage
from torch_geometric.transforms import BaseTransform

AttrNameType = str
NodeStoreType = str
EdgeStoreType = tuple
EdgeElemsType = str
PadValTypes = (float, int)
PadValUnion = Union[float, int]


class Padding(ABC):
    r"""Abstract class for specifying the padding values to use by :class:`Pad`
    transform.
    """
    @abstractmethod
    def __init__(self, *args, **kwargs):
        pass

    @abstractmethod
    def _validate(self):
        pass

    @abstractmethod
    def get_val(self, store_type=None, attr_name=None):
        pass


class MappingPadding(Padding):
    r"""Abstract class for specifying the padding values to use by :class:`Pad`
    transform. This class supports padding values represented as a dictionary.
    """
    key_types = ()
    val_types = ()

    def __init__(self, padding_values: Dict[Any, Any] = None,
                 default_value: PadValUnion = 0.0):
        if padding_values is None:
            padding_values = {}
        self.padding_values = padding_values
        self.default_value = default_value
        self._validate()
        self.padding_values = self.padding_values.copy()
        self._process()
        super().__init__(padding_values, default_value)

    def _validate(self):
        assert isinstance(self.padding_values, dict), \
            f'Attribute `padding_values` must be a dict but is ' \
            f'{type(self.padding_values)}.'
        for key, val in self.padding_values.items():
            self._validate_key_val(key, val)

    def _validate_key_val(self, key, val):
        assert isinstance(key, self.key_types), \
            f'Not all the types of `padding_values` keys are in ' \
            f'{self.key_types}.'
        assert isinstance(val, self.val_types), \
            f'Not all the types of `padding_values` values are in ' \
            f'{self.val_types}.'

    def _process(self):
        for key, pad_val in self.padding_values.items():
            if isinstance(pad_val, PadValTypes):
                self.padding_values[key] = UniformPadding(pad_val)

    def __repr__(self):
        return f'{self.__class__.__name__}' \
               f'(padding_values={self.padding_values}, ' \
               f'default_value={self.default_value})'


class UniformPadding(Padding):
    r"""Indicates uniform padding of all stores and atributes. To use with
    :class:`Pad` transform.

    Args:
        padding_values (int or float, optional): The value to be used for
            padding all the stores and attribites of the data object uniformly.
            (default: :obj:`0.0`)
    """
    def __init__(self, padding_values: PadValUnion = 0.0):
        self.padding_values = padding_values
        self._validate()
        super().__init__(padding_values)

    def _validate(self):
        assert isinstance(self.padding_values, PadValTypes), \
            f'Type of attribute `padding_values` must be one of ' \
            f'{PadValTypes} but is {type(self.padding_values)}.'

    def get_val(self, store_type=None, attr_name=None):
        return self.padding_values

    def __repr__(self):
        return f'{self.__class__.__name__}' \
               f'(padding_values={self.padding_values})'


class AttrNamePadding(MappingPadding):
    r"""Indicates specific padding values for different attribute names. To use
    with :class:`Pad` transform.

    Example:
        padding = AttrNamePadding(
            {'x': UniformPadding(3.0), 'y': 0.0},
            default_value=1.0)

    Args:
        padding_values (Dict[AttrNameType, Union[UniformPadding, int, float]],
            optional): The mapping from attribute names to padding values. If
            an attribute is not specified in the mapping, the
            :obj:`default_value` value is used. (default: :obj:`None`)
        default_value (PadValUnion, optional): The padding value used for
            attributes not specified in the :obj:`padding_values` mapping.
            (default: :obj:`0.0`)
    """
    key_types = (AttrNameType, )
    val_types = (UniformPadding, *PadValTypes)

    def __init__(self, padding_values: Dict[AttrNameType,
                                            Union[UniformPadding,
                                                  PadValUnion]] = None,
                 default_value: PadValUnion = 0.0):
        super().__init__(padding_values, default_value)

    def get_val(self, store_type=None, attr_name=None):
        if attr_name in self.padding_values.keys():
            return self.padding_values[attr_name].get_val()
        else:
            return self.default_value


class NodeTypePadding(MappingPadding):
    r"""Indicates specific padding values for different types of nodes. To use
    with :class:`Pad` transform for :class:`~torch_geometric.data.HeteroData`
    objects.

    Example:
        p1 = AttrNamePadding({'x': UniformPadding(3.0), 'y': 0.0})
        p2 = 3.0
        padding = NodeTypePadding(
            {'v1': p1, 'v2': p2},
            default_value=1.0)

    Args:
        padding_values (Dict[NodeStoreType, Union[UniformPadding, int, float,
            AttrNamePadding]], optional): The mapping from node types to
            padding values. If a node type is not specified in the mapping,
            the :obj:`default_value` value is used. (default: :obj:`None`)
        default_value (PadValUnion, optional): The padding value used for
            node types not specified in the :obj:`padding_values` mapping.
            (default: :obj:`0.0`)
    """
    key_types = (NodeStoreType, )
    val_types = (UniformPadding, AttrNamePadding, *PadValTypes)

    def __init__(self, padding_values: Dict[NodeStoreType,
                                            Union[UniformPadding, PadValUnion,
                                                  AttrNamePadding]] = None,
                 default_value=0.0):
        super().__init__(padding_values, default_value)

    def get_val(self, store_type=None, attr_name=None):
        if store_type in self.padding_values.keys():
            return self.padding_values[store_type].get_val(None, attr_name)
        else:
            return self.default_value


class EdgeTypePadding(MappingPadding):
    r"""Indicates specific padding values for different types of edges. To use
    with :class:`Pad` transform for :class:`~torch_geometric.data.HeteroData`
    objects.

    Example:
        p1 = AttrNamePadding({'edge_x': UniformPadding(3.0), 'edge_y': 0.0})
        p2 = -4.0
        padding = EdgeTypePadding(
            {('v1', 'e1', 'v2'): p1, ('v2', 'e1', 'v1'): p2},
            default_value=1.0)

    Args:
        padding_values (Dict[EdgeStoreType, Union[UniformPadding, int, float,
            AttrNamePadding]], optional): The mapping from edge types to
            padding values. If an edge type is not specified in the mapping,
            the :obj:`default_value` value is used. (default: :obj:`None`)
        default_value (PadValUnion, optional): The padding value used for
            edge types not specified in the :obj:`padding_values` mapping.
            (default: :obj:`0.0`)
    """
    key_types = (EdgeStoreType, )
    key_elem_types = (EdgeElemsType, )
    key_num_elems = 3
    val_types = (UniformPadding, AttrNamePadding, *PadValTypes)

    def __init__(self, padding_values: Dict[EdgeStoreType,
                                            Union[UniformPadding, PadValUnion,
                                                  AttrNamePadding]] = None,
                 default_value=0.0):
        super().__init__(padding_values, default_value)

    def _validate_key_val(self, key, val):
        super()._validate_key_val(key, val)
        assert len(key) == self.key_num_elems, \
            f'Invalid edge type. Should be a tuple with ' \
            f'{self.key_num_elems} elements but contains {len(key)} elements.'
        for key_elem in key:
            assert isinstance(key_elem, self.key_elem_types), \
                f'Not all the types of elements of `padding_values` ' \
                f'keys are in {self.key_elem_types}.'

    def get_val(self, store_type=None, attr_name=None):
        if store_type in self.padding_values.keys():
            return self.padding_values[store_type].get_val(None, attr_name)
        else:
            return self.default_value


@functional_transform('pad')
class Pad(BaseTransform):
    r"""Applies padding to enforce consistent tensor shapes
    (functional name: :obj:`pad`).

    This transform will pad node and edge features up to a maximum allowed size
    in the node or edge feature dimension. By default :obj:`0.0` is used as the
    padding value and can be configured by setting :obj:`node_pad_value` and
    :obj:`edge_pad_value`.

    In case of applying :class:`Pad` to a :class:`~torch_geometric.data.Data`
    object, the :obj:`node_pad_value` value (or :obj:`edge_pad_value`) can be
    either:

    * a float, int or object of :class:`UniformPadding` class for cases when
      all attributes are going to be padded with the same value;
    * an object of :class:`AttrNamePadding` class for cases when padding is
      going to differ based on attribute names.

    In case of applying :class:`Pad` to a
    :class:`~torch_geometric.data.HeteroData` object, the :obj:`node_pad_value`
    value (or :obj:`edge_pad_value`) can be either:

    * a float, int or object of :class:`UniformPadding` class for cases when
      all attributes of all node (or edge) stores are going to be padded with
      the same value;
    * an object of :class:`AttrNamePadding` class for cases when padding is
      going to differ based on attribute names and not based on a node
      (or edge) types;
    * an object of class :class:`NodeTypePadding` (or :class:`EdgeTypePadding`)
      for cases when padding values are going to differ based on a node
      (or edge) types. Padding values can also differ based on attribute names
      for a given node type by using objects of :class:`AttrNamePadding` class
      as values of `padding_values` argument of :class:`NodeTypePadding`
      (or :class:`EdgeTypePadding`) class.

    Note that in order to allow for at least one padding node for any padding
    edge, below conditions must be met:

    * if :obj:`max_num_nodes` is a single value, it must be greater than the
      maximum number of nodes of any graph in the dataset;
    * if :obj:`max_num_nodes` is a dictionary, value for every node type must
      be greater than the maximum number of this type nodes of any graph in the
      dataset.

    Args:
        max_num_nodes (int or Dict[NodeStoreType, int]): The number of nodes
            after padding.
            In heterogeneous graphs, may also take in a dictionary denoting the
            number of nodes for specific node types. The dictionary must
            specify values for all the possible node types.
        max_num_edges (int or Dict[EdgeStoreType, int], optional):
            The number of edges after padding. If not specified, the edges will
            be padded to a maximum size (creating a fully connected graph
            with loops).
            In heterogeneous graphs, may also take in a dictionary denoting the
            number of edges for specific edge types. If some edge type is not
            included in the dictionary, all the attributes of edges of that
            type will be padded to a maximum size. (default: :obj:`None`)
        node_pad_value (int or float or UniformPadding or AtrNamePadding,
            optional): The fill value to use for node features.
            (default: :obj:`0.0`)
        edge_pad_value (int or float or Padding, optional): The fill value to
            use for edge features. (default: :obj:`0.0`)
            Note that in case of :obj:`edge_index` attribute the tensors are
            padded with the index of the first padded node (which represents a
            set of self loops on the padded node).
        mask_pad_value (bool, optional): The fill value to use for
            :obj:`train_mask`, :obj:`val_mask` and :obj:`test_mask`
            (default: :obj:`False`).
        exclude_keys (List[str] or Tuple[str], optional): Keys to be removed
            from the input data object. (default: :obj:`None`)
    """
    def __init__(
        self,
        max_num_nodes: Union[int, Dict[str, int]],
        max_num_edges: Optional[Union[int, Dict[Tuple[str, str, str],
                                                int]]] = None,
        node_pad_value: Optional[Union[Padding, PadValUnion]] = None,
        edge_pad_value: Optional[Union[Padding, PadValUnion]] = None,
        mask_pad_value: Optional[bool] = None,
        exclude_keys: Optional[Union[List[str], Tuple[str]]] = None,
    ):
        super().__init__()

        self._default_pad_value = UniformPadding(0.0)
        self.max_num_nodes = self._NumNodes(max_num_nodes)
        self.max_num_edges = self._NumEdges(max_num_edges, self.max_num_nodes)

        self.exclude_keys = set(
            exclude_keys) if exclude_keys is not None else set()
        assert 'x' not in self.exclude_keys, \
            'Cannot create a `Pad` with `x` attribute being excluded.'

        self.node_pad = self._process_padding_argument(node_pad_value,
                                                       'node_pad_value')
        self.edge_pad = self._process_padding_argument(edge_pad_value,
                                                       'edge_pad_value')

        if mask_pad_value is None:
            mask_pad_value = 0.0
        mask_attrs = ['train_mask', 'val_mask', 'test_mask']
        self.node_additional_attrs_pad = {
            key: mask_pad_value
            for key in mask_attrs
        }

    def _process_padding_argument(self, padding: Any, name: str) -> Padding:
        if isinstance(padding, Padding):
            return padding
        if padding is None:
            return self._default_pad_value
        try:
            return UniformPadding(padding)
        except AssertionError as e:
            raise AssertionError(f'Invalid type of `{name}`.') from e

    class _IntOrDict(ABC):
        def __init__(self, value):
            self.value = value
            self.is_number = isinstance(value, numbers.Number)

        @abstractmethod
        def get_val(self, key):
            pass

        def is_none(self):
            return self.value is None

    class _NumNodes(_IntOrDict):
        def __init__(self, value):
            assert isinstance(value, (int, dict)), \
                f'Parameter `max_num_nodes` must be of type int or dict ' \
                f'but is {type(value)}.'
            super().__init__(value)

        def get_val(self, key=None):
            if self.is_number or self.value is None:
                # Homodata case.
                return self.value

            assert isinstance(key, str)
            assert key in self.value.keys(), \
                f'The number of {key} nodes was not specified for padding.'
            return self.value[key]

    class _NumEdges(_IntOrDict):
        def __init__(self, value: Union[int, Dict[EdgeStoreType, int], None],
                     num_nodes: '_NumNodes'):  # noqa: F821
            assert value is None or isinstance(value, (int, dict)), \
                f'If provided, parameter `max_num_edges` must be of type ' \
                f'int or dict but is {type(value)}.'

            if value is not None:
                if isinstance(value, int):
                    num_edges = value
                else:
                    num_edges = defaultdict(lambda: defaultdict(int))
                    for k, v in value.items():
                        src_node, edge_type, dst_node = k
                        num_edges[src_node, dst_node][edge_type] = v
            elif num_nodes.is_number:
                num_edges = num_nodes.get_val() * num_nodes.get_val()
            else:
                num_edges = defaultdict(lambda: defaultdict(int))

            self.num_nodes = num_nodes
            super().__init__(num_edges)

        def get_val(self, key=None):
            if self.is_number or self.value is None:
                # Homodata case.
                return self.value

            assert isinstance(key, tuple) and len(key) == 3
            src_v, edge_type, dst_v = key
            if (src_v, dst_v) in self.value.keys():
                if edge_type in self.value[src_v, dst_v]:
                    return self.value[src_v, dst_v][edge_type]

            max_num_edges = self.num_nodes.get_val(
                src_v) * self.num_nodes.get_val(dst_v)
            self.value[src_v, dst_v][edge_type] = max_num_edges
            return self.value[src_v, dst_v][edge_type]

    def __should_pad_node_attr(self, attr_name):
        if attr_name in self.node_additional_attrs_pad:
            return True
        if self.exclude_keys is None or attr_name not in self.exclude_keys:
            return True
        return False

    def __should_pad_edge_attr(self, attr_name):
        if self.max_num_edges.is_none():
            return False
        if attr_name == 'edge_index':
            return True
        if self.exclude_keys is None or attr_name not in self.exclude_keys:
            return True
        return False

    def __get_node_padding(self, attr_name, node_type=None):
        if attr_name in self.node_additional_attrs_pad:
            return self.node_additional_attrs_pad[attr_name]
        return self.node_pad.get_val(node_type, attr_name)

    def __get_edge_padding(self, attr_name, edge_type=None):
        return self.edge_pad.get_val(edge_type, attr_name)

    def __call__(self, data: Union[Data, HeteroData]):
        if isinstance(data, Data):
            assert isinstance(self.node_pad,
                              (UniformPadding, AttrNamePadding)), \
                f'Node padding for Data objects must be of type ' \
                f'UniformPadding or AttrNamePadding and is ' \
                f'{type(self.node_pad)}'
            assert isinstance(self.edge_pad,
                              (UniformPadding, AttrNamePadding)), \
                f'Edge padding for Data objects must be of type ' \
                f'UniformPadding or AttrNamePadding and is ' \
                f'{type(self.edge_pad)}'

            assert self.max_num_nodes.is_number, \
                f'Number of nodes for Data objects must be a number and is ' \
                f'of type {type(self.max_num_nodes.value)}'
            assert self.max_num_edges.is_number or \
                   self.max_num_edges.is_none(), \
                   'Number of edges for Data objects must be a number or None.'

            for store in data.stores:
                for key in self.exclude_keys:
                    if key in store.keys():
                        del store[key]
                self.__pad_edge_store(store, data.__cat_dim__, data.num_nodes)
                self.__pad_node_store(store, data.__cat_dim__)
        else:
            assert isinstance(
                self.node_pad,
                (UniformPadding, AttrNamePadding, NodeTypePadding))
            assert isinstance(
                self.edge_pad,
                (UniformPadding, AttrNamePadding, EdgeTypePadding))
            for edge_type, store in data.edge_items():
                for key in self.exclude_keys:
                    if key in store.keys():
                        del store[key]
                src_node_type, _, dst_node_type = edge_type
                self.__pad_edge_store(store, data.__cat_dim__,
                                      (data[src_node_type].num_nodes,
                                       data[dst_node_type].num_nodes),
                                      edge_type)
            for node_type, store in data.node_items():
                for key in self.exclude_keys:
                    if key in store.keys():
                        del store[key]
                self.__pad_node_store(store, data.__cat_dim__, node_type)
        return data

    def __pad_node_store(self, store: NodeStorage, get_dim_fn: Callable,
                         node_type: str = None):
        attrs_to_pad = [
            attr for attr in store.keys()
            if store.is_node_attr(attr) and self.__should_pad_node_attr(attr)
        ]
        if not attrs_to_pad:
            return
        num_target_nodes = self.max_num_nodes.get_val(node_type)
        assert num_target_nodes > store.num_nodes, \
            f'The number of nodes after padding ({num_target_nodes}) must ' \
            f'be greater than the number of nodes in the data object ' \
            f'({store.num_nodes}).'
        num_pad_nodes = num_target_nodes - store.num_nodes

        for attr_name in attrs_to_pad:
            attr = store[attr_name]
            pad_value = self.__get_node_padding(attr_name, node_type)
            dim = get_dim_fn(attr_name, attr)
            store[attr_name] = self._pad_tensor_dim(attr, dim, num_pad_nodes,
                                                    pad_value)

    def __pad_edge_store(self, store: EdgeStorage, get_dim_fn: Callable,
                         num_nodes: Union[int, Tuple[int, int]],
                         edge_type: str = None):
        attrs_to_pad = set(
            attr for attr in store.keys()
            if store.is_edge_attr(attr) and self.__should_pad_edge_attr(attr))
        if not attrs_to_pad:
            return
        num_target_edges = self.max_num_edges.get_val(edge_type)
        assert num_target_edges >= store.num_edges, \
            f'The number of edges after padding ({num_target_edges}) cannot ' \
            f'be lower than the number of edges in the data object ' \
            f'({store.num_edges}).'
        num_pad_edges = num_target_edges - store.num_edges

        if isinstance(num_nodes, tuple):
            src_pad_value, dst_pad_value = num_nodes
        else:
            src_pad_value = dst_pad_value = num_nodes

        for attr_name in attrs_to_pad:
            attr = store[attr_name]
            dim = get_dim_fn(attr_name, attr)
            if attr_name == 'edge_index':
                store[attr_name] = self._pad_edge_index(
                    attr, num_pad_edges, src_pad_value, dst_pad_value)
            else:
                pad_value = self.__get_edge_padding(attr_name, edge_type)
                store[attr_name] = self._pad_tensor_dim(
                    attr, dim, num_pad_edges, pad_value)

    @staticmethod
    def _pad_tensor_dim(input: torch.Tensor, dim: int, length: int,
                        pad_value: float) -> torch.Tensor:
        r"""Pads the input tensor in the specified dim with a constant value of
        the given length.
        """
        pads = [0] * (2 * input.ndim)
        pads[-2 * dim - 1] = length
        return F.pad(input, pads, 'constant', pad_value)

    @staticmethod
    def _pad_edge_index(input: torch.Tensor, length: int, src_pad_value: float,
                        dst_pad_value: float) -> torch.Tensor:
        r"""Pads the edges :obj:`edge_index` feature with values specified
        separately for src and dst nodes.
        """
        pads = [0, length, 0, 0]
        padded = F.pad(input, pads, 'constant', src_pad_value)
        if src_pad_value != dst_pad_value:
            padded[1, input.shape[1]:] = dst_pad_value
        return padded

    def __repr__(self) -> str:
        s = f'{self.__class__.__name__}('
        s += f'max_num_nodes={self.max_num_nodes.value}, '
        s += f'max_num_edges={self.max_num_edges.value}, '
        s += f'node_pad_value={self.node_pad}, '
        s += f'edge_pad_value={self.edge_pad})'
        return s
