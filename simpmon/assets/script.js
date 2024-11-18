// author: https://chatgpt.com/c/673117c9-112c-8013-a86b-0ab3cef4843a

// Map to store references to each chart by ID
const chartsMap = new Map();

// Function to create or update a chart for each data item
function createOrUpdateChart(data) {
    const chartId = `chart-${data.id}`; // Unique ID based on the UUID

    // Check if the chart already exists
    if (chartsMap.has(data.id)) {
        // Update the existing chart data and threshold annotations
        const chart = chartsMap.get(data.id);

        // Update the dataset data
        chart.data.datasets[0].data = data.values;

        // Clear existing threshold annotations
        chart.options.plugins.annotation.annotations = {};

        // Add new threshold annotations based on `alarms`
        data.alarms.forEach((alarm) => {
            const alarmName = alarm.name;
            chart.options.plugins.annotation.annotations[alarmName] = {
                type: "line",
                yMin: alarm.value,
                yMax: alarm.value,
                borderColor: alarmName === "Critical" ? "red" : "orange", // Different colors for different alarm levels
                borderWidth: 2,
                label: {
                    enabled: true,
                    content: alarmName,
                    position: "start",
                    backgroundColor:
                        alarmName === "Critical"
                            ? "rgba(255, 0, 0, 0.8)"
                            : "rgba(255, 165, 0, 0.8)",
                    color: "white",
                },
            };
        });

        // Update chart title and alarm label based on `active_alarm`
        const chartWrapper = document.getElementById(`wrapper-${chartId}`);
        const title = chartWrapper.querySelector("h2");
        title.textContent = data.title + (data.active_alarm ? " (ALARM)" : "");
        title.style.color = data.active_alarm ? "red" : "#333";

        // Update the "ALARM" label visibility
        const alarmLabel = chartWrapper.querySelector(".alarm-label");
        alarmLabel.style.display = data.active_alarm ? "block" : "none";

        // Update the red border based on `active_alarm`
        chartWrapper.style.border = data.active_alarm
            ? "3px solid red"
            : "none";

        // Refresh the chart to apply updates
        chart.update();
    } else {
        // Create a new chart if it doesn't exist
        const chartWrapper = document.createElement("div");
        chartWrapper.className = "chart-wrapper";
        chartWrapper.id = `wrapper-${chartId}`;

        // Set the initial red border if `active_alarm` is present
        if (data.active_alarm) {
            chartWrapper.style.border = "3px solid red";
        }

        // Add title with ALARM indication if `active_alarm` is not null
        const title = document.createElement("h2");
        title.textContent = data.title + (data.active_alarm ? " (ALARM)" : "");
        title.style.color = data.active_alarm ? "red" : "#333";
        title.style.fontWeight = "bold";
        chartWrapper.appendChild(title);

        // Add an "ALARM" label at the top of the chart if `active_alarm` is present
        const alarmLabel = document.createElement("div");
        alarmLabel.className = "alarm-label";
        alarmLabel.textContent = "ALARM";
        alarmLabel.style.position = "absolute";
        alarmLabel.style.top = "-10px";
        alarmLabel.style.left = "50%";
        alarmLabel.style.transform = "translateX(-50%)";
        alarmLabel.style.backgroundColor = "red";
        alarmLabel.style.color = "white";
        alarmLabel.style.padding = "5px 10px";
        alarmLabel.style.borderRadius = "5px";
        alarmLabel.style.fontWeight = "bold";
        alarmLabel.style.display = data.active_alarm ? "block" : "none";
        chartWrapper.appendChild(alarmLabel);

        // Create a canvas for the chart
        const canvas = document.createElement("canvas");
        canvas.id = chartId;
        chartWrapper.appendChild(canvas);

        // Prepare the threshold annotations based on `alarms`
        const thresholdAnnotations = {};
        data.alarms.forEach((alarm) => {
            const alarmName = alarm.name;
            thresholdAnnotations[alarmName] = {
                type: "line",
                yMin: alarm.value,
                yMax: alarm.value,
                borderColor: alarmName === "Critical" ? "red" : "orange",
                borderWidth: 2,
                label: {
                    enabled: true,
                    content: alarmName,
                    position: "start",
                    backgroundColor:
                        alarmName === "Critical"
                            ? "rgba(255, 0, 0, 0.8)"
                            : "rgba(255, 165, 0, 0.8)",
                    color: "white",
                },
            };
        });

        // Append the chart wrapper to the main container
        document.getElementById("chartsContainer").appendChild(chartWrapper);

        // Create the chart
        const ctx = canvas.getContext("2d");
        const chart = new Chart(ctx, {
            type: "line",
            data: {
                datasets: [
                    {
                        label: "Value over Time",
                        data: data.values,
                        fill: true,
                        borderColor: "#4a90e2",
                        backgroundColor: "rgba(74, 144, 226, 0.2)",
                        pointBackgroundColor: "#4a90e2",
                        pointBorderColor: "#fff",
                        pointHoverRadius: 5,
                        pointRadius: 4,
                        tension: 0.3,
                    },
                ],
            },
            options: {
                scales: {
                    x: {
                        type: "time",
                        time: {
                            unit: "minute",
                        },
                        title: {
                            display: true,
                            text: "Date",
                            color: "#333",
                            font: {
                                size: 14,
                            },
                        },
                        grid: {
                            color: "rgba(200, 200, 200, 0.2)",
                        },
                        ticks: {
                            color: "#666",
                        },
                    },
                    y: {
                        title: {
                            display: true,
                            text: data.unit,
                            color: "#333",
                            font: {
                                size: 14,
                            },
                        },
                        grid: {
                            color: "rgba(200, 200, 200, 0.2)",
                        },
                        ticks: {
                            color: "#666",
                        },
                    },
                },
                plugins: {
                    annotation: {
                        annotations: thresholdAnnotations, // Set annotations initially
                    },
                    legend: {
                        display: false, // Hide the legend entirely
                    },
                },
            },
        });

        // Store the chart in the map using `data.id`
        chartsMap.set(data.id, chart);
    }
}

// Function to fetch data from /status endpoint and update charts
async function fetchDataAndUpdateCharts() {
    try {
        const response = await fetch("/status");
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const dataItems = await response.json();

        // Update each chart based on the fetched data
        dataItems.forEach((data) => createOrUpdateChart(data));
    } catch (error) {
        console.error("Failed to fetch data:", error);
    }
}

// Call the function to fetch data and create charts initially
fetchDataAndUpdateCharts();

// Set up an interval to update charts every 5 seconds
setInterval(fetchDataAndUpdateCharts, 5000);
