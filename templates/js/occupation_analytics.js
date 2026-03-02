document.addEventListener("DOMContentLoaded", function () {

    loadCities();
    loadTrends();
    loadCompanies();
    loadLeadCities();
    loadOverlap();

});

async function loadCities() {
    const response = await fetch(`/api/jobs/cities/${occupationId}`);
    const data = await response.json();

    const labels = data.map(x => x.city);
    const counts = data.map(x => x.job_count);

    document.getElementById("kpi-total-cities").innerText = data.length;
    document.getElementById("kpi-total-jobs").innerText =
        counts.reduce((a, b) => a + b, 0);

    new Chart(document.getElementById("cityChart"), {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Job Count',
                data: counts
            }]
        }
    });
}

async function loadCompanies() {
    const response = await fetch(`/api/jobs/companies/${occupationId}`);
    const data = await response.json();

    const labels = data.map(x => x.company);
    const counts = data.map(x => x.job_count);

    document.getElementById("kpi-top-company").innerText =
        labels.length > 0 ? labels[0] : "-";

    new Chart(document.getElementById("companyChart"), {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Job Count',
                data: counts
            }]
        }
    });
}

async function loadLeadCities() {
    const response = await fetch(`/api/jobs/lead-cities/${occupationId}`);
    const data = await response.json();

    const table = document.getElementById("leadCitiesTable");

    data.forEach((city, index) => {
        table.innerHTML += `
            <tr>
                <td>${index + 1}</td>
                <td>${city.city}</td>
                <td>${city.job_count}</td>
            </tr>
        `;
    });
}

async function loadTrends() {
    const response = await fetch(`/api/jobs/trends/${occupationId}`);
    const data = await response.json();

    const labels = [...new Set(data.map(x => x.month))];

    const grouped = {};
    data.forEach(item => {
        if (!grouped[item.skill]) grouped[item.skill] = [];
        grouped[item.skill].push(item.count);
    });

    const datasets = Object.keys(grouped).map(skill => ({
        label: skill,
        data: grouped[skill],
        fill: false,
        tension: 0.3
    }));

    new Chart(document.getElementById("trendChart"), {
        type: 'line',
        data: {
            labels: labels,
            datasets: datasets
        }
    });
}

async function loadOverlap() {
    const response = await fetch(`/api/jobs/overlap/${occupationId}`);
    const data = await response.json();

    const labels = data.map(x => x.related_occupation);
    const scores = data.map(x => x.overlap_score);

    new Chart(document.getElementById("overlapChart"), {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Overlap Score',
                data: scores
            }]
        }
    });
}