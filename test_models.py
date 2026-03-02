# # -*- coding: utf-8 -*-
# """
# test_models.py  —  Run from ASGNPRAC root:
#     python test_models.py
#     python test_models.py --verbose
# """
# import sys, traceback

# def ok(msg):     print(f"  [PASS]  {msg}")
# def fail(msg):   print(f"  [FAIL]  {msg}")
# def info(msg):   print(f"       ->  {msg}")
# def header(msg): print(f"\n{'='*55}\n  {msg}\n{'='*55}")

# passed = 0
# failed = 0

# def check(label, fn):
#     global passed, failed
#     try:
#         result = fn()
#         ok(label)
#         if result is not None:
#             info(str(result))
#         passed += 1
#         return True
#     except Exception as e:
#         fail(label)
#         print(f"       ERROR: {type(e).__name__}: {e}")
#         if "--verbose" in sys.argv:
#             traceback.print_exc()
#         failed += 1
#         return False

# # ================================================================== #
# header("1 . IMPORTS")
# # ================================================================== #

# check("config loads",
#     lambda: __import__("config").settings.APP_NAME)

# check("database.py imports",
#     lambda: __import__("app.database", fromlist=["Base","get_db","SessionLocal"]))

# check("models.jobs imports",
#     lambda: __import__("app.models.jobs", fromlist=["JobPostLog","JobPostSkill"]))

# check("models.skills imports",
#     lambda: __import__("app.models.skills", fromlist=["EscoSkill","OscaOccupationSkill"]))

# check("models.osca imports",
#     lambda: __import__("app.models.osca", fromlist=["OscaOccupation","OscaMajorGroup"]))

# # ================================================================== #
# header("2 . DATABASE CONNECTION")
# # ================================================================== #

# from app.database import SessionLocal
# from sqlalchemy import text

# check("PostgreSQL reachable", lambda: SessionLocal().execute(text("SELECT version()")).scalar()[:60])
# check("Basic query executes", lambda: SessionLocal().execute(text("SELECT 1")) or "ping OK")

# # ================================================================== #
# header("3 . TABLE ROW COUNTS")
# # ================================================================== #

# from app.models.jobs   import JobPostLog, JobPostSkill
# from app.models.skills import EscoSkill, OscaOccupationSkill, OscaOccupationSkillSnapshot
# from app.models.osca   import (OscaMajorGroup, OscaSubMajorGroup, OscaMinorGroup,
#                                 OscaUnitGroup, OscaOccupation, OscaAlternativeTitle)

# EXPECTED = {
#     OscaMajorGroup:              (1,    20),
#     OscaSubMajorGroup:           (1,   100),
#     OscaMinorGroup:              (1,   200),
#     OscaUnitGroup:               (1,   400),
#     OscaOccupation:              (1000,2000),
#     OscaAlternativeTitle:        (1,   9999),
#     EscoSkill:                   (13000,15000),
#     OscaOccupationSkill:         (1,   9999),
#     OscaOccupationSkillSnapshot: (0,   9999),
#     JobPostLog:                  (4000,5000),
#     JobPostSkill:                (1,   9999),
# }

# for model, (lo, hi) in EXPECTED.items():
#     def count_rows(m=model, l=lo, h=hi):
#         db = SessionLocal()
#         try:
#             n = db.query(m).count()
#             suffix = f"  WARNING: expected {l:,}-{h:,}" if not (l <= n <= h) and not (n==0 and l==0) else ""
#             return f"{n:,} rows{suffix}"
#         finally:
#             db.close()
#     check(model.__tablename__, count_rows)

# # ================================================================== #
# header("4 . RELATIONSHIPS")
# # ================================================================== #

# def test_hierarchy():
#     db = SessionLocal()
#     try:
#         occ = db.query(OscaOccupation).filter(
#             OscaOccupation.principal_title == "Data Scientist").first()
#         if not occ:
#             return "WARNING: Data Scientist not found"
#         ug  = occ.unit_group
#         mg  = ug.minor_group       if ug  else None
#         smg = mg.sub_major_group   if mg  else None
#         maj = smg.major_group      if smg else None
#         return (f"Data Scientist -> {getattr(ug,'title','?')} -> "
#                 f"{getattr(mg,'title','?')} -> {getattr(maj,'title','?')}")
#     finally:
#         db.close()

# check("Occupation -> UnitGroup -> MinorGroup -> MajorGroup", test_hierarchy)

# def test_occ_skills():
#     db = SessionLocal()
#     try:
#         occ = (db.query(OscaOccupation)
#                .join(OscaOccupationSkill)
#                .filter(OscaOccupationSkill.mention_count > 0).first())
#         if not occ:
#             return "WARNING: no occupation with skills"
#         names = [s.skill.preferred_label for s in occ.occupation_skills[:3] if s.skill]
#         return f"{occ.principal_title!r} -> {names}"
#     finally:
#         db.close()

# check("Occupation -> OccupationSkills -> EscoSkill", test_occ_skills)

# def test_post_occupation():
#     db = SessionLocal()
#     try:
#         post = db.query(JobPostLog).filter(
#             JobPostLog.processed_by_ai == True,
#             JobPostLog.occupation_id.isnot(None)).first()
#         if not post:
#             return "WARNING: no AI-processed post with occupation"
#         title = post.occupation.principal_title if post.occupation else "N/A"
#         return f"JobPost {post.id} -> {title!r}"
#     finally:
#         db.close()

# check("JobPostLog -> OscaOccupation", test_post_occupation)

# def test_post_skills():
#     db = SessionLocal()
#     try:
#         post = db.query(JobPostLog).filter(JobPostLog.processed_by_ai == True).first()
#         if not post:
#             return "WARNING: no AI-processed posts"
#         return f"JobPost {post.id} has {len(post.post_skills)} skills"
#     finally:
#         db.close()

# check("JobPostLog -> JobPostSkill", test_post_skills)

# # ================================================================== #
# header("5 . BUSINESS QUERIES")
# # ================================================================== #

# def test_top_occupations():
#     from sqlalchemy import func
#     db = SessionLocal()
#     try:
#         rows = (db.query(
#                     OscaOccupation.principal_title,
#                     func.count(OscaOccupationSkill.skill_id).label("sc"),
#                     func.sum(OscaOccupationSkill.mention_count).label("tm"))
#                 .join(OscaOccupationSkill,
#                       OscaOccupationSkill.occupation_id == OscaOccupation.id)
#                 .group_by(OscaOccupation.principal_title)
#                 .order_by(func.sum(OscaOccupationSkill.mention_count).desc())
#                 .limit(5).all())
#         if not rows:
#             return "WARNING: no results"
#         return "\n         " + "\n         ".join(
#             f"{r.principal_title} ({r.sc} skills, {r.tm} mentions)" for r in rows)
#     finally:
#         db.close()

# check("Top 5 occupations by mention count", test_top_occupations)

# def test_rate():
#     db = SessionLocal()
#     try:
#         total = db.query(JobPostLog).count()
#         done  = db.query(JobPostLog).filter(JobPostLog.processed_by_ai == True).count()
#         return f"{done}/{total} ({round(done/total*100,2) if total else 0}%)"
#     finally:
#         db.close()

# check("Job post processing rate", test_rate)

# def test_skill_search():
#     db = SessionLocal()
#     try:
#         results = db.query(EscoSkill).filter(
#             EscoSkill.preferred_label.ilike("%python%")).limit(3).all()
#         return [s.preferred_label for s in results] or "WARNING: none found"
#     finally:
#         db.close()

# check("Skill search ilike python", test_skill_search)

# def test_traversal():
#     db = SessionLocal()
#     try:
#         majors = db.query(OscaMajorGroup).all()
#         total  = sum(len(ug.occupations)
#                      for m in majors
#                      for smg in m.sub_major_groups
#                      for mg in smg.minor_groups
#                      for ug in mg.unit_groups)
#         return f"{len(majors)} major groups -> {total} occupations reachable"
#     finally:
#         db.close()

# check("Full hierarchy traversal (sidebar simulation)", test_traversal)

# # ================================================================== #
# header("RESULTS")
# # ================================================================== #
# total = passed + failed
# print(f"  {passed} passed  /  {failed} failed  /  {total} total\n")
# if failed:
#     print("  Check [FAIL] lines above. Use --verbose for full tracebacks.\n")
#     sys.exit(1)
# else:
#     print("  All checks passed - ready to build routers.\n")
#     sys.exit(0)

# test_models.py — temporary test file, delete after testing
import logging
logging.basicConfig(level=logging.WARNING)  # suppress SQLAlchemy noise

from app.database import SessionLocal
from app.models.osca import (
    OscaMajorGroup, OscaSubMajorGroup, 
    OscaMinorGroup, OscaUnitGroup, OscaOccupation
)
from app.models.skills import EscoSkill, OscaOccupationSkill
from app.models.jobs import JobPostLog, JobPostSkill

db = SessionLocal()

print("\n=== Testing OSCA Models ===")
major_groups = db.query(OscaMajorGroup).all()
print(f"✅ Major Groups: {len(major_groups)}")
for mg in major_groups:
    print(f"   {mg.id} — {mg.title}")

print("\n=== Testing EscoSkill Model ===")
skills = db.query(EscoSkill).limit(3).all()
print(f"✅ Sample Skills:")
for s in skills:
    print(f"   {s.id} — {s.preferred_label} ({s.skill_type})")

print("\n=== Testing OccupationSkills Model ===")
top_occupations = (
    db.query(OscaOccupation)
    .join(OscaOccupationSkill)
    .order_by(OscaOccupationSkill.mention_count.desc())
    .limit(3)
    .all()
)
print(f"✅ Top Occupations by skill data:")
for o in top_occupations:
    print(f"   {o.id} — {o.principal_title}")

print("\n=== Testing JobPostLog Model ===")
processed = db.query(JobPostLog).filter(
    JobPostLog.processed_by_ai == True
).count()
total = db.query(JobPostLog).count()
print(f"✅ Job Posts: {processed}/{total} processed by AI")

db.close()
print("\n✅ All model tests passed!")