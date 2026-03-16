import logging
logging.basicConfig(level=logging.WARNING)

from app.database import SessionLocal
from app.services.skills_service import get_dashboard_summary, get_top_skills_for_occupation
from app.services.occupation_service import get_major_groups, get_sub_major_groups, get_occupations
# from app.services import skills_service
# from app.services import occupations_service

db = SessionLocal()
print("\n=== Testing Occupation Service ===")
major_groups = get_major_groups(db)
print(f"✅ Major Groups: {len(major_groups)}")
for mg in major_groups:
    print(f"   {mg['id']} — {mg['title']} ({mg['occupation_count']} occupations)")

print("\n=== Testing Sub-Major Groups ===")
sub_groups = get_sub_major_groups(db, major_group_id=1)
print(f"✅ Sub-Major Groups for Managers: {len(sub_groups)}")
for sg in sub_groups:
    print(f"   {sg['id']} — {sg['title']}")

print("\n=== Testing Occupation Search ===")
results = get_occupations(db, search="engineer")
print(f"✅ Occupations matching 'engineer': {len(results)}")
for o in results[:3]:
    print(f"   {o['id']} — {o['title']} (skills: {o['skill_count']})")

print("\n=== Testing Skills Service ===")
summary = get_dashboard_summary(db)
print(f"✅ Dashboard Summary:")
for key, val in summary.items():
    print(f"   {key}: {val}")

print("\n=== Testing Top Skills ===")
occupations_with_data = get_occupations(db)
occ_with_skills = [o for o in occupations_with_data if o['skill_count'] > 0]
if occ_with_skills:
    test_occ = occ_with_skills[0]
    print(f"✅ Testing with: {test_occ['title']}")
    skills = get_top_skills_for_occupation(db, test_occ['id'], limit=5)
    for s in skills:
        print(f"   {s['skill_name']} | mentions: {s['mention_count']} | score: {s['demand_score']}")

db.close()
print("\n✅ All service tests passed!")