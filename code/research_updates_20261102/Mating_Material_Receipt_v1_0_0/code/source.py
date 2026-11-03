"""Load the unmodified historical producers without their command-line entrypoints."""
import importlib.util,sys
from util import ROOT

def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/'vendor'/filename)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module
    spec.loader.exec_module(module);return module

core=load('material_receipt_original_core','receipt_core.py')
common=load('local_common','local_common.py')
absorption=load('matched_absorption','matched_absorption.py')
matched=load('material_receipt_original_matched','matched.py')
