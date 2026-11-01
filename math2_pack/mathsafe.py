"""Generic offline mathematical checks; no question bank, HTTP service or database.

These bounded AST and symbolic constraints are reused from the archived local
prototype, with no runtime import of legacy modules. All grades remain formative.
"""

from __future__ import annotations

import ast

import hashlib

import json

import sympy as s

def digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def item_digest(item):
    return digest({k: v for k, v in item.items() if k != "version_hash"})

SYMBOLS = {v: s.Symbol(v, real=True) for v in ("x", "y", "a", "b", "t", "u", "v", "z")}

FUNCS = {"sin":s.sin, "cos":s.cos, "tan":s.tan, "exp":s.exp, "log":s.log, "ln":s.log, "sqrt":s.sqrt, "abs":s.Abs}

def expression(raw):
    """Bounded AST interpreter. In particular, no eval/sympify of untrusted text."""
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        raise ValueError("需要有限标量或表达式")
    raw = str(raw).strip().replace("^", "**")
    if not raw or len(raw) > 300:
        raise ValueError("表达式为空或过长")
    try:
        tree = ast.parse(raw, mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise ValueError("表达式语法不受支持") from exc
    if sum(1 for _ in ast.walk(tree)) > 90:
        raise ValueError("表达式过于复杂")

    def visit(node, depth=0):
        if depth > 18:
            raise ValueError("表达式嵌套过深")
        if isinstance(node, ast.Expression): return visit(node.body, depth+1)
        if isinstance(node, ast.Constant) and type(node.value) in (int,float):
            if abs(node.value) > 10**12: raise ValueError("常数过大")
            result = s.Rational(str(node.value))
        elif isinstance(node, ast.Name):
            if node.id in SYMBOLS: return SYMBOLS[node.id]
            if node.id == "pi": return s.pi
            if node.id in ("e", "E"): return s.E
            raise ValueError("未许可符号")
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            v=visit(node.operand,depth+1); result=v if isinstance(node.op,ast.UAdd) else -v
        elif isinstance(node, ast.BinOp) and isinstance(node.op,(ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Pow)):
            left,right=visit(node.left,depth+1),visit(node.right,depth+1)
            if isinstance(node.op,ast.Add): result=left+right
            elif isinstance(node.op,ast.Sub): result=left-right
            elif isinstance(node.op,ast.Mult): result=left*right
            elif isinstance(node.op,ast.Div):
                if right == 0: raise ValueError("除以零")
                result=left/right
            else:
                if not right.is_number or abs(right)>12 or (left.is_number and abs(left)>10**6 and right>2): raise ValueError("指数超出本地核验范围")
                result=left**right
        elif isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in FUNCS and len(node.args)==1 and not node.keywords:
            arg=visit(node.args[0],depth+1)
            if node.func.id=="exp" and arg.is_number and abs(arg)>100: raise ValueError("指数参数过大")
            result=FUNCS[node.func.id](arg)
        else: raise ValueError("不支持的语法")
        if result.has(s.nan,s.zoo,s.oo,-s.oo) or result.is_real is False:
            raise ValueError("非有限实表达式")
        return result
    return visit(tree)

def matrix(raw, vector=False):
    if not isinstance(raw,list) or not raw or len(raw)>5:
        raise ValueError("需要不超过5阶矩阵")
    if vector and all(not isinstance(v,list) for v in raw):
        return s.Matrix([expression(v) for v in raw])
    if not all(isinstance(row,list) and row and len(row)<=5 for row in raw): raise ValueError("矩阵须为二维数组")
    if len({len(row) for row in raw})!=1: raise ValueError("矩阵行长不一致")
    return s.Matrix([[expression(v) for v in row] for row in raw])

def zero(v):
    if isinstance(v,s.MatrixBase): return all(s.simplify(e)==0 for e in v)
    return s.simplify(v)==0

def answer_symbol_names(value):
    """Retain symbols hidden by cancellation, e.g. t/t at an undefined point."""
    if isinstance(value,list):
        return set().union(*(answer_symbol_names(part) for part in value)) if value else set()
    if isinstance(value,str):
        try:
            tree=ast.parse(value.strip().replace("^","**"),mode="eval")
        except (SyntaxError,RecursionError) as exc:
            raise ValueError("无法解析矩阵系数") from exc
        return {n.id for n in ast.walk(tree) if isinstance(n,ast.Name) and n.id in SYMBOLS}
    return set()

def compare(value, field):
    kind=field["kind"]
    if kind=="enum": return isinstance(value,str) and value.strip().upper()==str(field["value"]).upper()
    if kind=="expr":
        actual=expression(value); expected=expression(field["value"])
        # Do not let symbolic cancellations manufacture a scalar answer such as
        # x/x=1 for a numeric result without any declared x domain.
        if isinstance(value,str):
            parsed=ast.parse(value.strip().replace("^","**"),mode="eval")
            named={n.id for n in ast.walk(parsed) if isinstance(n,ast.Name) and n.id in SYMBOLS}
            if not named<={str(v) for v in expected.free_symbols}: return False
        return zero(actual-expected)
    if kind=="vector":
        actual=matrix(value,True); target=matrix(field["value"],True)
        if answer_symbol_names(value)-{str(v) for v in target.free_symbols}: return False
        return actual.shape==target.shape and zero(actual-target)
    if kind=="particular":
        actual=matrix(value,True); A=matrix(field["matrix"]); b=matrix(field["rhs"],True)
        if answer_symbol_names(value) or actual.free_symbols: return False
        return actual.shape==(A.cols,1) and zero(A*actual-b)
    if kind=="span":
        actual=matrix(value); A=matrix(field["matrix"])
        # Generic symbolic rank assumes a parameter is nonzero. A numeric basis
        # cannot be certified from t*v when the undeclared t may be zero.
        if answer_symbol_names(value) or actual.free_symbols: return False
        nullity=A.cols-A.rank()
        return actual.rows==A.cols and actual.cols==nullity and actual.rank()==nullity and zero(A*actual)
    if kind=="orthogonal_eigenbasis":
        Q=matrix(value); A=matrix(field["matrix"]); eigen=field["eigenvalues"]
        if answer_symbol_names(value) or Q.free_symbols: return False
        if Q.shape!=A.shape: return False
        return zero(Q.T*Q-s.eye(A.rows)) and zero(A*Q-Q*s.diag(*eigen))
    raise ValueError("未知核验类型")

def check_answer(item, raw):
    result=dict(grade_status="PENDING_HUMAN_REVIEW", score=None, max_points=item["max_points"], complete=False, correct=None, first_divergence=None, dimensions={k:"UNKNOWN" for k in "RTMCF"}, error_codes=[], certificate="FORMATIVE_AI_PROVISIONAL", h0_status="PROVISIONAL_NOT_CERTIFIED", field_results=[], process_verified=False, confidence="LIMITED_STRUCTURED_CHECK_ONLY")
    if item.get("release_status")!="FORMATIVE_MACHINE_CHECKED" or not item.get("expected"):
        result["error_codes"]=["CONTENT_NOT_RELEASED"]; return result
    # Revalidate at grading, even if an in-memory caller altered a published dict.
    if item_digest(item)!=item.get("version_hash"):
        result["error_codes"]=["CONTENT_VERSION_MISMATCH"]; return result
    if not isinstance(raw,str) or len(raw)>20000 or not raw.strip():
        result.update(score=0, correct=False, error_codes=["BLANK_OR_INVALID"], first_divergence={"field":"submission","student":"空白或超长","expected":"独立作答及明确终值","cause":"尚无可核验答案"}); return result
    def no_duplicate_keys(pairs):
        out={}
        for key,value in pairs:
            if key in out: raise ValueError("重复答案字段："+key)
            out[key]=value
        return out
    try:
        data=json.loads(raw,object_pairs_hook=no_duplicate_keys)
    except ValueError as exc:
        if not isinstance(exc,json.JSONDecodeError):
            result["error_codes"]=["DUPLICATE_ANSWER_FIELDS"];return result
        if len(item["expected"])==1:
            data={next(iter(item["expected"])):raw.strip()}
        else:
            result.update(error_codes=["UNSUPPORTED_FREE_TEXT"],first_divergence={"field":"submission","student":raw[:400],"expected":"按题面字段提交JSON；自由推导保留待人工审阅","cause":"本地工具不能可靠理解自由文本推导"}); return result
    if not isinstance(data,dict):
        result["error_codes"]=["INVALID_ANSWER_OBJECT"]; return result
    if "answers" in data and set(data)-{"answers","work","work_text"}:
        result["error_codes"]=["UNSUPPORTED_ANSWER_FIELDS"];return result
    answers=data.get("answers",data)
    if not isinstance(answers,dict): result["error_codes"]=["INVALID_ANSWER_OBJECT"]; return result
    work=data.get("work",[])
    work_text=data.get("work_text","")
    if not isinstance(work_text,str) or len(work_text)>15000:
        result["error_codes"]=["UNSUPPORTED_PROCESS"];return result
    if not isinstance(work,list) or len(work)>24:
        result["error_codes"]=["UNSUPPORTED_PROCESS"]; return result
    # Any supplied mathematical assertion is checked before awarding results.
    for index,line in enumerate(work):
        try:
            if not isinstance(line,dict) or set(line)!={"lhs","rhs"}: raise ValueError("过程式须含lhs和rhs")
            lhs,rhs=expression(line["lhs"]),expression(line["rhs"])
            if not zero(lhs-rhs):
                result.update(score=0,correct=False,grade_status="FORMATIVE_AI_PROVISIONAL",error_codes=["R6_FALSE_EQUALITY"], first_divergence={"field":f"work[{index}]","student":line,"expected":"该步应为恒等式；不能由错误等式推出结论","cause":"此等式不成立，后续终值即使与答案相同也不能获得过程认可"}); return result
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            result["error_codes"]=["UNSUPPORTED_PROCESS"]; result["first_divergence"]={"field":f"work[{index}]","student":str(line)[:300],"expected":"可核验的实数恒等式","cause":str(exc)}; return result
    expected_keys=set(item["expected"])
    extras=set(answers)-expected_keys-{"work","answers","work_text"}
    if extras:
        result["error_codes"]=["UNSUPPORTED_ANSWER_FIELDS"]
        result["first_divergence"]={"field":sorted(extras)[0],"student":str(answers[sorted(extras)[0]])[:200],"expected":"只允许题面明确要求的答案字段；其余文字作为原答保留待审","cause":"额外终值或自由过程可能与结构答案矛盾，拒绝自动得分"}
        return result
    correct_count=0
    for name,field in item["expected"].items():
        present=name in answers
        detail="缺少本题要求的终值/中间量"
        try:
            ok=present and compare(answers[name],field)
            if present: detail="结构化结果核验一致" if ok else "表达式、条件、维数或矩阵约束不成立"
        except (ValueError,TypeError,s.ShapeError,ZeroDivisionError,OverflowError) as exc:
            ok=False; detail="无法可靠核验："+str(exc)
        result["field_results"].append(dict(field=name,correct=bool(ok),present=present,detail=detail,points=item["max_points"]/len(expected_keys) if ok else 0,confidence="SYMBOLIC_CONSTRAINT_CHECK"))
        if not ok:
            result["dimensions"][field["dimension"]]="BREAKPOINT"
        elif result["dimensions"][field["dimension"]]!="BREAKPOINT":
            result["dimensions"][field["dimension"]]="PROVISIONAL_CORRECT"
        if ok: correct_count+=1
        elif result["first_divergence"] is None:
            result["first_divergence"]={"field":name,"student":answers.get(name,"未填写"),"expected":field["value"],"cause":detail,"dimension":field["dimension"]}
    all_present=all(k in answers for k in expected_keys)
    result.update(grade_status="FORMATIVE_AI_PROVISIONAL",score=round(item["max_points"]*correct_count/len(expected_keys),3),complete=all_present,correct=correct_count==len(expected_keys),process_verified=False,provided_equalities_verified=bool(work),first_divergence_scope="STRUCTURED_FIELD_OR_EXPLICIT_EQUALITY_ONLY")
    if not result["correct"]: result["error_codes"]=["R6_CHAIN_BREAK" if not all_present else "R7_RESULT_MISMATCH"]
    if work_text.strip():
        # Visible mathematics in a free narrative may contradict an otherwise
        # correct result. Preserve the finite field check without certifying the
        # whole solution or silently awarding full process credit.
        result["result_score"]=result["score"]
        result["result_correct"]=result["correct"]
        result.update(grade_status="PENDING_HUMAN_REVIEW",score=None,correct=None,process_verified=False,review_required=True,process_note="自由推导已原样封存；结果字段核验不代表整段解答正确，须可靠人工审阅。")
    return result

def validate_math(item):
    """Recompute explicit mathematical models, not source 'PASS' flags."""
    x,y,a=SYMBOLS["x"],SYMBOLS["y"],SYMBOLS["a"]
    model=item["model"]; typ=model["type"]; got={}
    if typ in ("limit_implicit","implicit_shape"):
        F=expression(model["implicit"]); x0,y0=model["point"]
        fy=s.diff(F,y); dy=-s.diff(F,x)/fy
        ddy=-(s.diff(F,x,2)+2*s.diff(F,x,y)*dy+s.diff(F,y,2)*dy**2)/fy
        if typ=="limit_implicit":
            got={"limit":s.limit(expression(model["limit_expr"]),x,0),"dy":dy.subs({x:x0,y:y0}),"ddy":ddy.subs({x:x0,y:y0})}
        else:
            val=ddy.subs({x:x0,y:y0}); got={"k":dy.subs({x:x0,y:y0}),"c":val,"shape":"UP" if val>0 else "DOWN"}
    elif typ=="removable":
        f=expression(model["function"]); val=s.limit(f,x,0); got={"a":val,"b":s.limit((f-val)/x,x,0),"c":s.limit(expression(model["other"]),x,0)}
    elif typ=="log_optimization":
        f=expression(model["f"]); deriv=s.diff(f,x); stationary=s.solve(deriv,x)[0]; tangent=s.solve(deriv-expression(model["tangent_slope"]),x)[0]
        got={"x0":stationary,"m":f.subs(x,stationary),"xt":tangent,"b":"NONE" if tangent<=0 else f.subs(x,tangent)-model["tangent_slope"]*tangent}
    elif typ=="integral_volume":
        lo,hi=model["bounds"]; got={"I":s.integrate(expression(model["integrand"]),(x,lo,hi)),"V":s.pi*s.integrate(expression(model["upper"])**2-expression(model["lower"])**2,(x,lo,hi))}
    elif typ=="improper_substitution":
        p=expression(model["p"]); got={"c":1 if p<1 else 0,"I":sum(expression(n)**(1-p)/(1-p) for n in (model["left_length"],model["right_length"])),"J":s.Rational(1,model["power"]+1)}
    elif typ=="ode":
        candidate=expression(item["expected"]["y"]["value"]); residual=sum(expression(c)*s.diff(candidate,x,k) for k,c in enumerate(model["coeffs"]))-expression(model["rhs"])
        assert zero(residual),"ODE residual"
        at,*initial=model["initial"]
        for k,value in enumerate(initial): assert zero(s.diff(candidate,x,k).subs(x,at)-value),"ODE initial condition"
        got={"y":candidate,"v":candidate.subs(x,expression(model["eval_at"]))}
    elif typ in ("double_chain","scalar_double"):
        expr=expression(model.get("integrand",model.get("expr"))); ya,yb=[expression(v) for v in model["y_bounds"]]
        value=s.integrate(s.integrate(expr,(y,ya,yb)),(x,*model["x_bounds"]))
        got={"I" if typ=="double_chain" else "value":value}
        if typ=="double_chain":
            (ux,uy),(vx,vy)=model["linear_uv"]; got.update(a=ux*uy,b=ux*vy+vx*uy,c=vx*vy)
    elif typ=="disk_quadratic":
        A=matrix(model["quad_A"]); linear=matrix(model["linear"],True); p=-A.inv()*linear/2; minimum=(p.T*A*p+linear.T*p)[0]
        got={"I":2*s.pi*expression(model["radius"])**(model["radial_power"]+2)/(model["radial_power"]+2),"s":p[0],"t":p[1],"m":minimum}
    elif typ=="parameter_kernel":
        A=matrix(model["A"]); got={"det":A.det(),"r0":A.subs(a,0).rank(),"r1":A.subs(a,1).rank()}
    elif typ=="affine_same_kernel":
        A,B=matrix(model["A"]),matrix(model["B"])
        got={"same":int(A.row_join(s.zeros(A.rows,0)).rank()==B.rank() and A.col_join(B).rank()==A.rank())}
    elif typ in ("symmetric_spectral","spectral_bridge"):
        A=matrix(model["A"]); eig=sorted([k for k,n in A.eigenvals().items() for _ in range(n)])
        got={"Lambda":eig,"pd":int(all(v>0 for v in eig))}
        if "det" in item["expected"]: got["det"]=A.det()
    elif typ=="scalar_limit": got={"value":s.limit(expression(model["expr"]),x,0)}
    elif typ=="derivative":
        d=s.diff(expression(model["expr"]),x);got={"d":d,"v":d.subs(x,0)}
    elif typ=="scalar_integral": got={"value":s.integrate(expression(model["expr"]),(x,*model["bounds"]))}
    elif typ=="kernel_bridge": got={"r":matrix(model["A"]).rank()}
    else: raise AssertionError("Unimplemented independent model: "+typ)
    checks=[]
    for key,field in item["expected"].items():
        if key in got:
            actual=got[key]
            if isinstance(actual,s.Basic): actual=str(actual)
            elif isinstance(actual,list): actual=[str(v) for v in actual]
            assert compare(actual,field),f"{item['id']} field {key} recomputation differs: {actual} vs {field}"
        elif field["kind"] in ("span","particular","orthogonal_eigenbasis"):
            assert compare(field["value"],field),f"{item['id']} invalid {key}"
        else: raise AssertionError(f"Unverified {item['id']} {key}")
        checks.append(key)
    assert sum(r["points"] for r in item["rubric"])==item["max_points"] or abs(sum(r["points"] for r in item["rubric"])-item["max_points"])<1e-8
    assert len(item["solution"]["solution_steps"])>=3
    return {"id":item["id"],"fields_recomputed":checks,"status":"PASS","human_review":"NOT_PERFORMED","h0_eligible":False}
