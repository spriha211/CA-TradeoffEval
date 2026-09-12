from __future__ import annotations

import csv
import hashlib
import json
import platform
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from src.cross_model_replication.generate import PROTOCOL, PROTOCOL_SHA256, ROOT, RUN_ROOT
from src.cross_model_replication.lock_scores import LOCK_ROOT

MEASURES = ("M03", "M08", "M02", "M09", "M05")
EXPECTED_COMPONENTS = {"M03": 58, "M08": 28, "M02": 65, "M09": 25, "M05": 64}
CONDITIONS = ("single_agent", "independent_ensemble", "normal_debate", "critic_debate")
LABELS = {"single_agent": "Single agent", "independent_ensemble": "Independent ensemble", "normal_debate": "Normal debate", "critic_debate": "Critic debate"}
CONDITION_KEYS = {"setup1_single": "single_agent", "setup2_independent": "independent_ensemble", "setup3_debate": "normal_debate", "setup4_critic": "critic_debate"}
CONTRASTS = (
    ("independent_ensemble_minus_single_agent", "independent_ensemble", "single_agent"),
    ("normal_debate_minus_independent_ensemble", "normal_debate", "independent_ensemble"),
    ("critic_debate_minus_normal_debate", "critic_debate", "normal_debate"),
)
CONTRAST_LABELS = {"independent_ensemble_minus_single_agent": "Independent − single", "normal_debate_minus_independent_ensemble": "Normal debate − independent", "critic_debate_minus_normal_debate": "Critic debate − normal debate"}
OUTCOMES = ("claim_weighted_preservation", "component_weighted_preservation", "mean_component_distortion_severity", "any_distortion_rate", "material_distortion_rate")
PRE = ROOT / "runs/audits/cross_model_replication/STUDY2_PRE_UNBLIND_INTEGRITY_MANIFEST.json"
PRE_SHA = "181a4f13298d2a997346ea71e4e8ca5d3b2148ebeb8be3da3c47623bf1c01fa1"
OUT = ROOT / "results/cross_model_replication/claude_sonnet_5/post_lock_analysis"
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20_260_809


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict]) -> None:
    if path.exists(): raise FileExistsError(f"Refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)


def write_text(path: Path, text: str) -> None:
    if path.exists(): raise FileExistsError(f"Refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding="utf-8")


def gate() -> dict:
    if sha(PRE) != PRE_SHA or sha(PROTOCOL) != PROTOCOL_SHA256: raise RuntimeError("Study 2 final gate hash mismatch")
    pre = json.loads(PRE.read_text())
    if not (pre["status"] == "PASS" and pre["measure_count"] == 5 and pre["total_blinded_outputs"] == 80 and pre["total_locked_scoring_rows"] == 3840 and pre["unresolved_flag_count"] == 0):
        raise RuntimeError("Study 2 final gate requirements failed")
    for item in pre["measures"]:
        if sha(ROOT / item["locked_scoring_csv"]) != item["locked_scoring_sha256"] or sha(ROOT / item["scoring_lock_manifest"]) != item["scoring_lock_manifest_sha256"] or sha(ROOT / item["review_log"]) != item["review_log_sha256"]:
            raise RuntimeError(f"Post-lock input changed: {item['measure_id']}")
    return pre


def load_inputs() -> tuple[list[dict], list[dict], dict[str, str], str]:
    gate()
    inputs = {str(PRE.relative_to(ROOT)): sha(PRE), str(PROTOCOL.relative_to(ROOT)): sha(PROTOCOL)}
    mapping_records, master, returned_models = [], [], set()
    for measure in MEASURES:
        mapping_path = RUN_ROOT / "sealed_private_mappings" / f"{measure}_blind_mapping_private.json"
        mapping_data = json.loads(mapping_path.read_text(encoding="utf-8"))
        inputs[str(mapping_path.relative_to(ROOT))] = sha(mapping_path)
        mapping = {}
        for entry in mapping_data["entries"]:
            condition = CONDITION_KEYS.get(entry["condition"]); trial = int(entry["trial_number"])
            if condition is None or not 1 <= trial <= 4: raise RuntimeError("Invalid sealed Study 2 mapping entry")
            record = {"measure_id": measure, "blind_id": entry["blind_id"], "trial_number": trial, "trial_id": f"{measure}-trial{trial:02d}", "condition": condition}
            mapping[entry["blind_id"]] = record; mapping_records.append(record)
        if len(mapping) != 16 or len({(x["condition"], x["trial_number"]) for x in mapping.values()}) != 16: raise RuntimeError(f"Unbalanced mapping: {measure}")
        lock_manifest_path = LOCK_ROOT / measure / f"{measure}_scoring_lock_manifest.json"
        lock = json.loads(lock_manifest_path.read_text()); locked_path = ROOT / lock["locked_scoring_csv"]
        component_path = ROOT / "data/reference_inventories" / f"{measure}_components.csv"
        for path in (lock_manifest_path, locked_path, component_path, ROOT / lock["review_log"]): inputs[str(path.relative_to(ROOT))] = sha(path)
        components = {row["component_id"]: row for row in read_csv(component_path)}; locked = read_csv(locked_path)
        if len(components) != EXPECTED_COMPONENTS[measure] or len(locked) != 16 * EXPECTED_COMPONENTS[measure]: raise RuntimeError(f"Input count mismatch: {measure}")
        seen = set()
        for row in locked:
            key = (row["blind_id"], row["component_id"])
            if key in seen or row["blind_id"] not in mapping or row["component_id"] not in components: raise RuntimeError(f"Invalid locked join: {measure} {key}")
            seen.add(key); identity = mapping[row["blind_id"]]; component = components[row["component_id"]]
            master.append({**identity, "condition_label": LABELS[identity["condition"]], "claim_id": component["claim_id"], "component_id": row["component_id"], "preservation_score": int(row["preservation_score"]), "distortion_score": int(row["distortion_score"])})
        for trial in range(1, 5):
            generation = RUN_ROOT / "generation" / measure / f"trial{trial:02d}" / "complete.json"
            inputs[str(generation.relative_to(ROOT))] = sha(generation)
            returned_models.update(json.loads(generation.read_text())["returned_models"])
    if len(master) != 3840 or len({(r["measure_id"], r["blind_id"], r["component_id"]) for r in master}) != 3840: raise RuntimeError("Master row integrity failed")
    if returned_models != {"claude-sonnet-5"}: raise RuntimeError(f"Unexpected Claude model identifiers: {returned_models}")
    return master, mapping_records, inputs, next(iter(returned_models))


def output_metrics(master: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    for row in master: grouped[(row["measure_id"], row["blind_id"])].append(row)
    output = []
    for _, rows in sorted(grouped.items()):
        first = rows[0]; claims = defaultdict(list)
        for row in rows: claims[row["claim_id"]].append(row["preservation_score"])
        preservation = np.array([r["preservation_score"] for r in rows], float); distortion = np.array([r["distortion_score"] for r in rows], float)
        output.append({"measure_id": first["measure_id"], "trial_id": first["trial_id"], "trial_number": first["trial_number"], "blind_id": first["blind_id"], "condition": first["condition"], "condition_label": first["condition_label"], "claim_weighted_preservation": float(np.mean([np.mean(v) for v in claims.values()])), "component_weighted_preservation": float(preservation.mean()), "mean_component_distortion_severity": float(distortion.mean()), "any_distortion_rate": float((distortion > 0).mean()), "material_distortion_rate": float((distortion == 2).mean()), "n_claims": len(claims), "n_components": len(rows)})
    if len(output) != 80: raise RuntimeError("Expected 80 output summaries")
    for measure in MEASURES:
        rows = [r for r in output if r["measure_id"] == measure]
        if len(rows) != 16 or {r["condition"] for r in rows} != set(CONDITIONS): raise RuntimeError(f"Condition balance failed: {measure}")
        for condition in CONDITIONS:
            if {r["trial_number"] for r in rows if r["condition"] == condition} != {1,2,3,4}: raise RuntimeError(f"Trial balance failed: {measure} {condition}")
    return output


def summaries(outputs: list[dict]) -> tuple[list[dict], list[dict]]:
    groups = defaultdict(list)
    for row in outputs: groups[(row["measure_id"], row["condition"])].append(row)
    mc = []
    for (measure, condition), rows in sorted(groups.items()):
        result = {"measure_id": measure, "condition": condition, "condition_label": LABELS[condition], "n_trials": 4, "n_components_per_output": rows[0]["n_components"], "n_claims_per_output": rows[0]["n_claims"]}
        for outcome in OUTCOMES:
            values=np.array([r[outcome] for r in rows]); result[outcome]=float(values.mean()); result[f"{outcome}_sd_across_trials"]=float(values.std(ddof=1))
        mc.append(result)
    cs=[]
    for condition in CONDITIONS:
        rows=[r for r in mc if r["condition"]==condition]; result={"condition":condition,"condition_label":LABELS[condition],"n_measures":5,"n_outputs":20}
        for outcome in OUTCOMES:
            values=np.array([r[outcome] for r in rows]); result[outcome]=float(values.mean()); result[f"{outcome}_sd_across_measures"]=float(values.std(ddof=1))
        cs.append(result)
    return mc,cs


def contrast_tables(mc: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    lookup={(r["measure_id"],r["condition"]):r for r in mc}; paired=[]
    for measure in MEASURES:
        for name,upper,lower in CONTRASTS:
            row={"measure_id":measure,"contrast":name,"contrast_label":CONTRAST_LABELS[name],"n_trials_per_condition":4}
            for outcome in OUTCOMES: row[f"{outcome}_difference"]=lookup[(measure,upper)][outcome]-lookup[(measure,lower)][outcome]
            paired.append(row)
    rng=np.random.default_rng(BOOTSTRAP_SEED); samples=rng.integers(0,5,size=(BOOTSTRAP_REPLICATES,5)); aggregate=[]; lomo=[]
    for name,_,_ in CONTRASTS:
        rows=[r for r in paired if r["contrast"]==name]
        for outcome in OUTCOMES:
            field=f"{outcome}_difference"; values=np.array([r[field] for r in rows],float); estimate=float(values.mean()); boot=values[samples].mean(axis=1); low,high=np.percentile(boot,[2.5,97.5]); lv=np.array([np.delete(values,i).mean() for i in range(5)]); direction_change=bool(any(np.sign(v)!=np.sign(estimate) for v in lv))
            aggregate.append({"contrast":name,"contrast_label":CONTRAST_LABELS[name],"outcome":outcome,"mean_paired_difference":estimate,"sd_across_measure_differences":float(values.std(ddof=1)),"bootstrap_ci_95_low":float(low),"bootstrap_ci_95_high":float(high),"n_measures":5,"bootstrap_replicates":BOOTSTRAP_REPLICATES,"bootstrap_seed":BOOTSTRAP_SEED,"positive_measure_differences":int((values>0).sum()),"negative_measure_differences":int((values<0).sum()),"zero_measure_differences":int((values==0).sum())})
            for i,omitted in enumerate(MEASURES): lomo.append({"contrast":name,"contrast_label":CONTRAST_LABELS[name],"outcome":outcome,"omitted_measure_id":omitted,"leave_one_out_mean_difference":float(lv[i]),"full_sample_mean_difference":estimate,"lomo_minimum":float(lv.min()),"lomo_maximum":float(lv.max()),"direction_changes_in_any_omission":direction_change,"n_measures_after_omission":4})
    return paired,aggregate,lomo


def comparison(aggregate: list[dict]) -> list[dict]:
    study1_path=ROOT/"results/post_lock_analysis/aggregate_contrasts.csv"; study1=read_csv(study1_path)
    rows=[]
    specs=[("independent_ensemble_minus_single_agent","claim_weighted_preservation"),("normal_debate_minus_independent_ensemble","claim_weighted_preservation"),("critic_debate_minus_normal_debate","claim_weighted_preservation"),("critic_debate_minus_normal_debate","component_weighted_preservation")]
    for contrast,outcome in specs:
        a=next(r for r in study1 if r["contrast"]==contrast and r["outcome"]==outcome); b=next(r for r in aggregate if r["contrast"]==contrast and r["outcome"]==outcome)
        aeff=float(a["mean_paired_difference"]); al=float(a["bootstrap_ci_95_low"]); ah=float(a["bootstrap_ci_95_high"]); beff=b["mean_paired_difference"]
        rows.append({"contrast":contrast,"outcome":outcome,"study1_model":"GPT","study1_n_measures":10,"study1_effect":aeff,"study1_ci_low":al,"study1_ci_high":ah,"study1_ci_includes_zero":al<=0<=ah,"study1_positive_negative_tied":f"{a['positive_measure_differences']}/{a['negative_measure_differences']}/{a['zero_measure_differences']}","study2_model":"Claude Sonnet 5","study2_n_measures":5,"study2_effect":beff,"study2_ci_low":b["bootstrap_ci_95_low"],"study2_ci_high":b["bootstrap_ci_95_high"],"study2_ci_includes_zero":b["bootstrap_ci_95_low"]<=0<=b["bootstrap_ci_95_high"],"study2_positive_negative_tied":f"{b['positive_measure_differences']}/{b['negative_measure_differences']}/{b['zero_measure_differences']}","directions_match":bool(np.sign(aeff)==np.sign(beff)),"study2_minus_study1_effect":beff-aeff,"comparison_type":"descriptive; no pooled estimate"})
    return rows


def style() -> None:
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":9,"axes.spines.top":False,"axes.spines.right":False,"figure.dpi":160,"savefig.dpi":300})


def save(fig, base: Path) -> list[Path]:
    paths=[]
    for ext in ("svg","pdf","png"):
        p=base.with_suffix(f".{ext}")
        if p.exists(): raise FileExistsError(f"Refusing overwrite: {p}")
        fig.savefig(p,bbox_inches="tight",facecolor="white"); paths.append(p)
    plt.close(fig); return paths


def figures(mc: list[dict], paired: list[dict], aggregate: list[dict], cross: list[dict]) -> list[Path]:
    style(); paths=[]; lookup={(r["measure_id"],r["condition"]):r for r in mc}; x=np.arange(4)
    fig,ax=plt.subplots(figsize=(7.2,4.5))
    for m in MEASURES: ax.plot(x,[lookup[(m,c)]["claim_weighted_preservation"] for c in CONDITIONS],color="#8a99a8",alpha=.65,marker="o",linewidth=1)
    ax.plot(x,[np.mean([lookup[(m,c)]["claim_weighted_preservation"] for m in MEASURES]) for c in CONDITIONS],color="#1261a0",marker="o",linewidth=2.5,label="Claude mean")
    ax.set_xticks(x,[LABELS[c] for c in CONDITIONS]); ax.set_ylim(0,1); ax.set_ylabel("Claim-weighted preservation"); ax.set_title("Study 2 Claude condition means"); ax.grid(axis="y",alpha=.25); ax.legend(frameon=False); paths+=save(fig,OUT/"figures/figureA_claude_condition_means")
    fig,ax=plt.subplots(figsize=(7.2,4.5))
    for i,(name,_,_) in enumerate(CONTRASTS):
        vals=[r["claim_weighted_preservation_difference"] for r in paired if r["contrast"]==name]; ax.scatter(np.full(5,i)+np.linspace(-.12,.12,5),vals,color="#687b8c")
        a=next(r for r in aggregate if r["contrast"]==name and r["outcome"]=="claim_weighted_preservation"); e=a["mean_paired_difference"]; ax.errorbar(i,e,yerr=[[e-a["bootstrap_ci_95_low"]],[a["bootstrap_ci_95_high"]-e]],fmt="D",color="#b23a48",capsize=5,linewidth=2)
    ax.axhline(0,color="#333",linewidth=.8); ax.set_xticks(range(3),[CONTRAST_LABELS[c[0]] for c in CONTRASTS]); ax.set_ylabel("Paired claim-weighted difference"); ax.set_title("Study 2 paired contrasts (95% measure-bootstrap CIs)"); ax.grid(axis="y",alpha=.25); paths+=save(fig,OUT/"figures/figureB_claude_paired_contrasts")
    for outcome,label,filename in (("claim_weighted_preservation","Claim-weighted critic − normal","figureC_gpt_vs_claude_primary"),("component_weighted_preservation","Component-weighted critic − normal","figureD_component_weighted_comparison")):
        row=next(r for r in cross if r["contrast"]=="critic_debate_minus_normal_debate" and r["outcome"]==outcome); fig,ax=plt.subplots(figsize=(5.8,4.2)); effects=[row["study1_effect"],row["study2_effect"]]; lows=[row["study1_ci_low"],row["study2_ci_low"]]; highs=[row["study1_ci_high"],row["study2_ci_high"]]
        ax.errorbar([0,1],effects,yerr=[[effects[i]-lows[i] for i in range(2)],[highs[i]-effects[i] for i in range(2)]],fmt="D",color="#1261a0",capsize=6,linewidth=2); ax.axhline(0,color="#333",linewidth=.8); ax.set_xticks([0,1],["Study 1 GPT\n(n=10 measures)","Study 2 Claude\n(n=5 measures)"]); ax.set_ylabel("Paired preservation difference"); ax.set_title(label); ax.grid(axis="y",alpha=.25); paths+=save(fig,OUT/f"figures/{filename}")
    return paths


def result_text(condition: list[dict], aggregate: list[dict], lomo: list[dict], cross: list[dict]) -> list[Path]:
    fmt=lambda x:f"{x:.4f}"; primary=next(r for r in aggregate if r["contrast"]=="critic_debate_minus_normal_debate" and r["outcome"]=="claim_weighted_preservation"); pl=next(r for r in lomo if r["contrast"]==primary["contrast"] and r["outcome"]==primary["outcome"])
    lines=["# Study 2 Results Summary","","Study 2 is a post-confirmatory external replication using Claude Sonnet 5. It is reported separately from Study 1.","","## Observed results",""]
    for r in condition: lines.append(f"- {r['condition_label']}: claim-weighted {fmt(r['claim_weighted_preservation'])}; component-weighted {fmt(r['component_weighted_preservation'])}; mean distortion severity {fmt(r['mean_component_distortion_severity'])}; any-distortion rate {fmt(r['any_distortion_rate'])}; material-distortion rate {fmt(r['material_distortion_rate'])}.")
    lines += ["","## Paired contrasts and uncertainty",""]
    for name,_,_ in CONTRASTS:
        r=next(x for x in aggregate if x["contrast"]==name and x["outcome"]=="claim_weighted_preservation"); lines.append(f"- {r['contrast_label']}: {fmt(r['mean_paired_difference'])}, 95% CI [{fmt(r['bootstrap_ci_95_low'])}, {fmt(r['bootstrap_ci_95_high'])}]; measure directions +/−/tie = {r['positive_measure_differences']}/{r['negative_measure_differences']}/{r['zero_measure_differences']}.")
    comp=next(x for x in aggregate if x["contrast"]=="critic_debate_minus_normal_debate" and x["outcome"]=="component_weighted_preservation"); lines += ["",f"Component-weighted critic − normal: {fmt(comp['mean_paired_difference'])}, 95% CI [{fmt(comp['bootstrap_ci_95_low'])}, {fmt(comp['bootstrap_ci_95_high'])}].",f"Primary LOMO range [{fmt(pl['lomo_minimum'])}, {fmt(pl['lomo_maximum'])}]; direction changed under omission: {'yes' if pl['direction_changes_in_any_omission'] else 'no'}.","","## Interpretation",""]
    pcomp=next(r for r in cross if r["contrast"]=="critic_debate_minus_normal_debate" and r["outcome"]=="claim_weighted_preservation"); lines.append(f"Study 1 GPT estimated {fmt(pcomp['study1_effect'])} [{fmt(pcomp['study1_ci_low'])}, {fmt(pcomp['study1_ci_high'])}]; Study 2 Claude estimated {fmt(pcomp['study2_effect'])} [{fmt(pcomp['study2_ci_low'])}, {fmt(pcomp['study2_ci_high'])}]. Directions {'matched' if pcomp['directions_match'] else 'did not match'}; the descriptive Study 2-minus-Study 1 difference was {fmt(pcomp['study2_minus_study1_effect'])}. No pooled estimate or formal cross-study test was used. With five measures, uncertainty and heterogeneity should not be overstated.")
    summary=OUT/"STUDY2_RESULTS_SUMMARY.md"; write_text(summary,"\n".join(lines)+"\n")
    paper=["# Cross-Model Paper Results","", "| Outcome / contrast | Study 1 GPT | Study 2 Claude | Direction match |","|---|---:|---:|---:|"]
    for r in cross: paper.append(f"| {CONTRAST_LABELS[r['contrast']]} — {r['outcome'].replace('_',' ')} | {fmt(r['study1_effect'])} [{fmt(r['study1_ci_low'])}, {fmt(r['study1_ci_high'])}] | {fmt(r['study2_effect'])} [{fmt(r['study2_ci_low'])}, {fmt(r['study2_ci_high'])}] | {'Yes' if r['directions_match'] else 'No'} |")
    paper += ["","Study 2 is a separate post-confirmatory external replication. Estimates were not pooled. Confidence intervals use the reused Study 1 procedure: 10,000 paired measure-level bootstrap replicates, seed 20260809.",""]
    pp=OUT/"CROSS_MODEL_PAPER_RESULTS.md"; write_text(pp,"\n".join(paper)); return [summary,pp]


def main() -> None:
    if OUT.exists() and any(OUT.iterdir()): raise FileExistsError(f"Refusing overwrite: {OUT}")
    OUT.mkdir(parents=True,exist_ok=True); (OUT/"figures").mkdir(); (OUT/"audits").mkdir()
    master,mappings,input_hashes,model=load_inputs(); script=Path(__file__).resolve(); input_hashes["results/post_lock_analysis/aggregate_contrasts.csv"]=sha(ROOT/"results/post_lock_analysis/aggregate_contrasts.csv")
    git={"commit":subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,text=True,capture_output=True,check=True).stdout.strip(),"worktree_status":subprocess.run(["git","status","--short"],cwd=ROOT,text=True,capture_output=True,check=True).stdout.strip()}
    unblind=OUT/"audits/STUDY2_UNBLINDING_AUDIT_MANIFEST.json"
    write_text(unblind,json.dumps({"schema_version":"1.0","unblinded_at_utc":datetime.now(timezone.utc).isoformat(),"pre_unblind_integrity_manifest":{"path":str(PRE.relative_to(ROOT)),"sha256":PRE_SHA},"protocol":{"path":str(PROTOCOL.relative_to(ROOT)),"sha256":PROTOCOL_SHA256},"mapping_files":[{"path":str((RUN_ROOT/"sealed_private_mappings"/f"{m}_blind_mapping_private.json").relative_to(ROOT)),"sha256":input_hashes[str((RUN_ROOT/"sealed_private_mappings"/f"{m}_blind_mapping_private.json").relative_to(ROOT))]} for m in MEASURES],"locked_scoring_inputs":[{"measure_id":m,"path":str((LOCK_ROOT/m/f"{m}_locked_scoring.csv").relative_to(ROOT)),"sha256":input_hashes[str((LOCK_ROOT/m/f"{m}_locked_scoring.csv").relative_to(ROOT))]} for m in MEASURES],"blind_id_measure_trial_condition_mapping":mappings,"exact_generation_model_identifier":model,"analysis_code":{"path":str(script.relative_to(ROOT)),"sha256":sha(script)},"code_version":git},indent=2,sort_keys=True)+"\n")
    trial=output_metrics(master); mc,cs=summaries(trial); paired,aggregate,lomo=contrast_tables(mc); cross=comparison(aggregate)
    artifacts=[unblind]
    for name,rows in (("master_analysis_table.csv",master),("trial_level_summary.csv",trial),("measure_condition_summary.csv",mc),("condition_summary.csv",cs),("paired_contrasts.csv",paired),("aggregate_contrasts.csv",aggregate),("leave_one_measure_out.csv",lomo),("CROSS_MODEL_COMPARISON.csv",cross)):
        path=OUT/name; write_csv(path,rows); artifacts.append(path)
    artifacts += figures(mc,paired,aggregate,cross); artifacts += result_text(cs,aggregate,lomo,cross)
    checks={"final_gate_pass":True,"five_measures":len({r['measure_id'] for r in master})==5,"eighty_outputs":len(trial)==80,"3840_locked_rows":len(master)==3840,"four_conditions_per_measure":all(len([r for r in mc if r['measure_id']==m])==4 for m in MEASURES),"four_trials_per_measure_condition":all(r['n_trials']==4 for r in mc),"no_duplicate_master_keys":len({(r['measure_id'],r['blind_id'],r['component_id']) for r in master})==3840,"fifteen_measure_contrasts":len(paired)==15,"fifteen_aggregate_outcomes":len(aggregate)==15,"seventy_five_lomo_rows":len(lomo)==75,"no_p_values_or_pooling":True}
    if not all(checks.values()): raise RuntimeError(f"Analysis checks failed: {checks}")
    manifest=OUT/"STUDY2_POST_UNBLIND_ANALYSIS_MANIFEST.json"
    write_text(manifest,json.dumps({"schema_version":"1.0","created_at_utc":datetime.now(timezone.utc).isoformat(),"status":"PASS","study":"Study 2 external replication","input_hashes":input_hashes,"mapping_hashes":{str((RUN_ROOT/"sealed_private_mappings"/f"{m}_blind_mapping_private.json").relative_to(ROOT)):input_hashes[str((RUN_ROOT/"sealed_private_mappings"/f"{m}_blind_mapping_private.json").relative_to(ROOT))] for m in MEASURES},"analysis_scripts":[{"path":str(script.relative_to(ROOT)),"sha256":sha(script)}],"generated_artifacts":[{"path":str(p.relative_to(ROOT)),"sha256":sha(p)} for p in artifacts],"bootstrap":{"replicates":BOOTSTRAP_REPLICATES,"seed":BOOTSTRAP_SEED,"resampling_unit":"measure","measures_sampled_per_replicate":5,"interval":"95% percentile","provenance":"reused already-fixed Study 1 analysis procedure"},"versions":{"python":platform.python_version(),"numpy":np.__version__,"matplotlib":plt.matplotlib.__version__,**git},"integrity_checks":checks,"warnings":["Study 2 has five measures and is reported separately from Study 1.","Cross-model comparisons are descriptive; no pooled estimate or formal cross-study test."]},indent=2,sort_keys=True)+"\n")
    print(manifest)


if __name__=="__main__": main()
