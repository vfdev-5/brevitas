from typing import Tuple, Union, Optional
from abc import ABC
from packaging import version

import torch
from torch import Tensor
from torch.nn import Module

from brevitas.quant_tensor import QuantTensor
from brevitas.utils.jit_utils import jit_trace_patched


def _override_quant_metadata_caching_mode(m: Module, enabled: bool):
    if hasattr(m, 'cache_quant_io_metadata_only'):
        if not hasattr(m, "cache_quant_io_metadata_only_backup"):
            m.cache_quant_io_metadata_only_backup = m.cache_quant_io_metadata_only
            m.cache_quant_io_metadata_only = enabled


def _override_bias_caching_mode(m: Module, enabled: bool):
    if hasattr(m, 'cache_inference_quant_bias'):
        if not hasattr(m, "cache_inference_quant_bias_backup"):
            m.cache_inference_quant_bias_backup = m.cache_inference_quant_bias
            m.cache_inference_quant_bias = enabled


def _override_inp_caching_mode(m: Module, enabled: bool):
    if hasattr(m, 'cache_inference_quant_inp'):
        if not hasattr(m, "cache_inference_quant_inp_backup"):
            m.cache_inference_quant_inp_backup = m.cache_inference_quant_inp
            m.cache_inference_quant_inp = enabled


def _override_out_caching_mode(m: Module, enabled: bool):
    if hasattr(m, 'cache_inference_quant_out'):
        if not hasattr(m, "cache_inference_quant_out_backup"):
            m.cache_inference_quant_out_backup = m.cache_inference_quant_out
            m.cache_inference_quant_out = enabled


def _restore_quant_metadata_caching_mode(m: Module):
    if hasattr(m, "cache_quant_io_metadata_only_backup"):
        m.cache_quant_io_metadata_only = m.cache_quant_io_metadata_only_backup
        del m.cache_quant_io_metadata_only_backup


def _restore_bias_caching_mode(m: Module):
    if hasattr(m, "cache_inference_quant_bias_backup"):
        m.cache_inference_quant_bias = m.cache_inference_quant_bias_backup
        del m.cache_inference_quant_bias_backup


def _restore_inp_caching_mode(m: Module):
    if hasattr(m, "cache_inference_quant_inp_backup"):
        m.cache_inference_quant_inp = m.cache_inference_quant_inp_backup
        del m.cache_inference_quant_inp_backup


def _restore_out_caching_mode(m: Module):
    if hasattr(m, "cache_inference_quant_out_backup"):
        m.cache_inference_quant_out = m.cache_inference_quant_out_backup
        del m.cache_inference_quant_out_backup


def _set_export_mode(m: Module, enabled: bool):
    if hasattr(m, 'export_mode'):
        m.export_mode = enabled


class BaseManager(ABC):

    handlers = []

    @classmethod
    def handler_from_module(cls, module: Module):
        for handler in cls.handlers:
            if isinstance(module, handler.handled_layer):
                return handler
        return None

    @classmethod
    def set_export_handler(cls, module: Module):
        if hasattr(module, 'export_handler') and module.export_handler is None:
            handler = cls.handler_from_module(module)
            if handler is None and module.requires_export_handler:
                raise RuntimeError(f"Module {module.__class__} not supported for export.")
            elif handler is None and not module.requires_export_handler:
                pass
            else:
                module.export_handler = handler()

    @classmethod
    def cache_inp_out(cls, module, input_t):
        # force enable caching
        module.apply(lambda m: _override_quant_metadata_caching_mode(m, enabled=True))
        module.apply(lambda m: _override_bias_caching_mode(m, enabled=True))
        module.apply(lambda m: _override_inp_caching_mode(m, enabled=True))
        module.apply(lambda m: _override_out_caching_mode(m, enabled=True))
        _ = module.forward(input_t)
        # Restore previous caching properties
        module.apply(lambda m: _restore_quant_metadata_caching_mode(m))
        module.apply(lambda m: _restore_bias_caching_mode(m))
        module.apply(lambda m: _restore_inp_caching_mode(m))
        module.apply(lambda m: _restore_out_caching_mode(m))

    @classmethod
    def jit_trace(cls, module: Module, input_t: Union[Tensor, QuantTensor]):
        with torch.no_grad():
            module = module.eval()
            module.apply(cls.set_export_handler)
            # do a forward pass with the dummy input to e.g. store input/output shapes
            cls.cache_inp_out(module, input_t)
            # override any given input_t to make sure it's a standard PyTorch tensor
            input_shape = input_t.shape if isinstance(input_t, Tensor) else input_t.value.shape
            input_t = torch.empty(input_shape, dtype=torch.float)
            # enable export mode, this triggers collecting export values into handlers
            module.apply(lambda m: _set_export_mode(m, enabled=True))
            traced_model = jit_trace_patched(module, input_t)
            module.apply(lambda m: _set_export_mode(m, enabled=False))
            return traced_model