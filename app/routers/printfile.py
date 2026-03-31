import os
import asyncio
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates
from playwright.async_api import async_playwright

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.post("/export-pdf/{occupation_id}")
async def export_occupation_pdf(request: Request, occupation_id: int):
    # user choices from the request body
    body = await request.json()
    include_top = body.get("include_top_skills", True)
    include_overlap = body.get("include_overlap", True)

    # Fetch database data
    # heatmap_data = get_heatmap_data(db, occupation_id)
    # top_skills = get_hot_skills(db, days=30)
    heatmap_data = [] # get_overlap_data(occupation_id) 
    top_skills = []    # get_top_skills(occupation_id, limit=20)
    occ_name = "Data Scientist" # get_occupation_name(occupation_id)
    
    # Render HTML using Jinja2 (Directly to a string)
    template_vars = {
        "request": request,
        "include_top": include_top,
        "include_overlap": include_overlap,
        "heatmap_data": heatmap_data, # Pass raw Python data
        "top_skills": top_skills,
        "occ_name": "Data Scientist" # Example
    }
    
    # We use .get_template() + .render() to get a string
    html_content = templates.get_template("print_report.html").render(template_vars)

    # Use Playwright to turn that string into a PDF
    pdf_filename = f"report_{occupation_id}.pdf"
    pdf_path = os.path.join("outputs", pdf_filename)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        #  set_content for petter performance, injecting the hltlf file
        await page.set_content(html_content, wait_until="networkidle")
        
        # Wait for D3 to finish drawing (if overlap is included)
        if show_overlap:
            await page.wait_for_selector(".jt-heatmap-table", timeout=5000)

        await page.pdf(
            path=pdf_path, 
            format="A4", 
            print_background=True,
            margin={"top": "1cm", "bottom": "1cm", "left": "1cm", "right": "1cm"}
        )
        await browser.close()

    return FileResponse(pdf_path, filename=f"{occ_name}_Report.pdf")