"""Offline tests for bounded geometry repair, candidate aids and explicit variables."""
import copy
import json
import logging
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pymupdf

from pipeline.variable_contract import check
from pipeline.geometry_candidates import attach
from pipeline.steps.s1_locate import scheme_edge_issues, annotate_scheme_issues
from pipeline.steps.s2_common import thread_usage
from pipeline.steps.s2_extract import _Job
from pipeline.config import CodexConfig


class VariableContract(unittest.TestCase):
    def inv(self):
        return {"columns": [{"key": "p", "kind": "participant"},
                            {"key": "x", "kind": "variable", "variable_name": "X"}],
                "template": {"variable_defaults": []},
                "entries": [{"label": "4", "descriptor": "4; X=H; 90; 50", "cells": [
                    {"column": "p", "text": ""}, {"column": "x", "text": "X=H"}]},
                    {"label": "5", "descriptor": "5; X=OMe; 91; 51", "cells": [
                    {"column": "p", "text": ""}, {"column": "x", "text": "X=OMe"}]}]}

    def resolve(self, inv, row):
        return {c["column"]: c for c in inv["entries"][row-1]["cells"]}

    def test_correct_explicit_variables_unchanged(self):
        inv=self.inv();before=copy.deepcopy(inv)
        self.assertEqual(check(inv,self.resolve),[])
        self.assertEqual(inv,before)

    def test_descriptive_only_assignment_and_wrong_value_are_rejected(self):
        inv=self.inv();inv["entries"][1]["cells"][1]["text"]=""
        self.assertIn("X=OMe",check(inv,self.resolve)[0])
        inv["entries"][1]["cells"][1]["text"]="X=H"
        self.assertTrue(check(inv,self.resolve))

    def test_default_cannot_hide_wrong_row_value(self):
        inv=self.inv();inv["template"]["variable_defaults"]=[{"name":"X","value":"OMe"}]
        inv["entries"][1]["cells"][1]["text"]="X=H"
        self.assertTrue(check(inv,self.resolve))

    def test_no_blind_repair_or_false_quantity_extraction(self):
        inv=self.inv()
        for row in inv["entries"]:
            row["descriptor"]="yield = 90%; 1 h"
            row["cells"][1]["text"]=""
        self.assertEqual(check(inv,self.resolve),[])


class GeometryCandidates(unittest.TestCase):
    def test_candidates_are_proposals_within_page(self):
        pdf=pymupdf.open();page=pdf.new_page(width=300,height=300)
        page.draw_rect(pymupdf.Rect(30,40,70,90));page.insert_text((72,65),"Cl")
        job=SimpleNamespace(pdf_lock=threading.Lock(),_page=lambda doc,n:page)
        with tempfile.TemporaryDirectory() as tmp:
            images,note=attach(job,"main",{"page":1,"bbox":[20,20,120,120]},None,Path(tmp))
            data=json.loads((Path(tmp)/"candidates.json").read_text())
            self.assertTrue(data["proposals_only"]);self.assertTrue(images[0].exists())
            self.assertTrue(data["pages"][0]["candidates"])
            self.assertIn("proposals",note)
        pdf.close()

    def test_locate_edges_are_keyed_for_local_propagation(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf=pymupdf.open();page=pdf.new_page();page.draw_line((30,70),(180,70),width=3)
            path=Path(tmp)/"p.pdf";pdf.save(path);pdf.close()
            schemes=[{"doc":"main","page":1,"scheme_id":"bad","bbox":[90,50,200,90]},
                     {"doc":"main","page":1,"scheme_id":"good","bbox":[20,50,200,90]}]
            issues=scheme_edge_issues({"schemes":schemes},{"main":{"pdf":str(path)}})
            self.assertEqual(set(issues),{"bad"})
            data={"regions":[{"blocks":[{"scheme_id":"bad","include":True},
                                           {"scheme_id":"good","include":True}]}]}
            annotate_scheme_issues(data,issues)
            bad,good=data["regions"][0]["blocks"]
            self.assertIn("locate_geometry_issues",bad)
            self.assertNotIn("locate_geometry_issues",good)
            self.assertTrue(bad["include"] and good["include"])


class BoundedRepair(unittest.TestCase):
    def test_geometry_only_callback_is_chosen_and_usage_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cfg=SimpleNamespace(codex=CodexConfig(max_repair_rounds=1))
            job=SimpleNamespace(out=root,cfg=cfg,ws=SimpleNamespace(root=root))
            result=SimpleNamespace(data={"bbox":[1],"value":43},thread_id="original",usage={"input_tokens":10},salvaged=False)
            def repair(data,n,errors):
                return {**data,"bbox":[2]}, {"thread_id":"geometry","usage":{"input_tokens":7}}
            def validate(data):return (["box edge: clipped"] if data["bbox"]==[1] else []),[]
            with patch("pipeline.steps.s2_extract.run_codex",return_value=result),patch("pipeline.steps.s2_extract.resume_codex") as resume:
                answer,meta=_Job._codex(job,root/"schema.json","prompt",[],root/"raw.json",root/"events",10,validate,geometry_repair=repair)
            resume.assert_not_called();self.assertEqual(answer["value"],43);self.assertEqual(meta["status"],"ok")
            self.assertEqual(meta["usage"]["input_tokens"],17)
            self.assertEqual(thread_usage([meta])["input_tokens"],17)

    def test_semantic_errors_never_use_geometry_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);job=SimpleNamespace(out=root,cfg=SimpleNamespace(codex=CodexConfig(max_repair_rounds=1)),ws=SimpleNamespace(root=root))
            result=SimpleNamespace(data={"x":0},thread_id="original",usage={},salvaged=False)
            final=SimpleNamespace(data={"x":1},thread_id="original",usage={},salvaged=False)
            with patch("pipeline.steps.s2_extract.run_codex",return_value=result),patch("pipeline.steps.s2_extract.resume_codex",return_value=final),patch("builtins.print"):
                repair=unittest.mock.Mock()
                _,meta=_Job._codex(job,root/"schema","prompt",[],root/"raw",root/"events",10,
                    lambda d:(["variable contract: missing"] if not d["x"] else [],[]),geometry_repair=repair)
                repair.assert_not_called();self.assertEqual(meta["status"],"ok")


if __name__=="__main__":unittest.main()
