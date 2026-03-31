import sys
import os
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates
from playwright.async_api import async_playwright
from sqlalchemy.orm import Session


sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logger import get_logger
from app.database import get_db
from app.services.jobs_service import get_skill_overlap, get_hot_skills_for_occupation

logger = get_logger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.post("/api/export-pdf/{occupation_id}")
async def export_occupation_pdf(request: Request, occupation_id: int, db: Session = Depends(get_db)):
    try:
        logger.info(f"Starting PDF export for occupation_id: {occupation_id}")
        body = await request.json()
        occ_name = body.get("occupation_name", "Occupation_Report")

        #Fetch Real Data from services
        heatmap_data = get_skill_overlap(db, occupation_id)
        top_skills_data = get_hot_skills_for_occupation(db, occupation_id)

        #Template Variables
        template_vars = {
            "request": request,
            "occ_name": occ_name,
            "include_trends": body.get("include_top_skills", True),
            "include_overlap": body.get("include_overlap", True),
            "trends": top_skills_data, # {% for s in skills_data.skills %}
            "heatmap": heatmap_data,         #  {{ heatmap.occupations }}
        }

        # Render HTML
        html_content = templates.get_template("print_report.html").render(template_vars)

        # Playwright to generate PDF
        os.makedirs("exports", exist_ok=True)
        # Use a path inside the exports folder
        pdf_path = f"exports/report_{occupation_id}.pdf"
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = await browser.new_page()
            
            # Injecting the rendered HTML
            await page.set_content(html_content, wait_until="networkidle")
            
            #  Wait for CSS container class to ensure content is ready
            await page.wait_for_selector(".pdf-body", timeout=5000)

            await page.pdf(
                path=pdf_path, 
                format="A4", 
                print_background=True,
                margin={"top": "1cm", "bottom": "1cm", "left": "1cm", "right": "1cm"}
            )
            await browser.close()
        logger.info(f"PDF successfully generated: {pdf_path} for {occ_name}")

        # Clean filename for the download
        safe_name = occ_name.replace(" ", "_")
        return FileResponse(pdf_path, filename=f"{safe_name}_Report.pdf")

    except Exception as e: 
        logger.error(f"CRITICAL ERROR in export_occupation_pdf {occupation_id}: {str(e)}", exc_info=True)
        # Log the full traceback needed here for later
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")