// bulk_reassign.js
// Lógica para interceptar y gestionar la reasignación en bloque de citas futuras.

let bulkReassignState = {
    appointments: [],
    availableBarbers: [],
    deactivateEndpoint: '',
    deactivatePayload: {},
    csrfToken: '',
    onSuccessCallback: null
};

/**
 * Initializes and shows the bulk reassign modal.
 */
function initBulkReassign(data, endpoint, payload, csrf, onSuccess) {
    bulkReassignState.appointments = data.appointments;
    bulkReassignState.availableBarbers = data.available_barbers;
    bulkReassignState.deactivateEndpoint = endpoint;
    bulkReassignState.deactivatePayload = payload || {};
    bulkReassignState.csrfToken = csrf;
    bulkReassignState.onSuccessCallback = onSuccess;
    
    renderBulkReassignList();
    document.getElementById('modal-bulk-reassign').classList.remove('hidden');
}

/**
 * Closes the bulk reassign modal.
 */
function closeBulkReassignModal() {
    document.getElementById('modal-bulk-reassign').classList.add('hidden');
    bulkReassignState.appointments = [];
}
window.cancelBulkReassign = closeBulkReassignModal;

/**
 * Checks if a barber is available given a start time and duration.
 */
function isBarberAvailable(barber, startTimeIso, durationMins) {
    const start = new Date(startTimeIso);
    const end = new Date(start.getTime() + durationMins * 60000);
    
    // 1. Check existing future appointments (overlaps)
    for (let app of barber.future_appointments) {
        const appStart = new Date(app.start_time);
        const appEnd = new Date(app.end_time);
        if (start < appEnd && end > appStart) return false;
    }

    // 2. Check exceptions (overlaps)
    for (let exc of barber.exceptions) {
        const exStart = new Date(exc.start);
        const exEnd = new Date(exc.end);
        if (start < exEnd && end > exStart) return false;
    }

    // 3. Check if within work schedule
    // Python day_of_week: 0=Monday, 6=Sunday. JS getDay(): 0=Sunday, 1=Monday... 6=Saturday.
    const pyDayOfWeek = start.getDay() === 0 ? 6 : start.getDay() - 1;
    let hasSchedule = false;
    
    // Convert to minutes from midnight in local time for easy comparison
    const startMins = start.getHours() * 60 + start.getMinutes();
    const endMins = startMins + durationMins;

    for (let sch of barber.schedules) {
        if (sch.day_of_week === pyDayOfWeek) {
            const [sh, sm] = sch.start_time.split(':');
            const schStartMins = parseInt(sh, 10) * 60 + parseInt(sm, 10);
            
            const [eh, em] = sch.end_time.split(':');
            const schEndMins = parseInt(eh, 10) * 60 + parseInt(em, 10);
            
            if (startMins >= schStartMins && endMins <= schEndMins) {
                hasSchedule = true;
                break;
            }
        }
    }
    
    // If the barber has no schedules defined at all, we assume they are available 
    // to avoid completely hiding them, but if they do have schedules, enforce them.
    if (!hasSchedule && barber.schedules.length > 0) {
        return false;
    }

    return true;
}

/**
 * Updates the action UI for a specific row.
 */
function updateRowActionState(appId, action) {
    const select = document.getElementById(`bulk-reassign-select-${appId}`);
    const btnCancel = document.getElementById(`bulk-reassign-cancel-${appId}`);
    const row = document.getElementById(`bulk-row-${appId}`);
    
    if (action === 'cancel') {
        select.value = '';
        select.disabled = true;
        select.classList.add('opacity-50');
        btnCancel.classList.remove('text-neutral-500', 'hover:text-red-400');
        btnCancel.classList.add('text-red-500', 'bg-red-500/10');
        btnCancel.dataset.state = 'cancelled';
        if (row) {
            row.classList.remove('bg-neutral-800/30', 'border-neutral-700/50', 'bg-green-500/5', 'border-green-500/30');
            row.classList.add('bg-red-500/5', 'border-red-500/30');
        }
    } else {
        select.disabled = false;
        select.classList.remove('opacity-50');
        btnCancel.classList.remove('text-red-500', 'bg-red-500/10');
        btnCancel.classList.add('text-neutral-500', 'hover:text-red-400');
        btnCancel.dataset.state = 'active';
        if (row) {
            row.classList.remove('bg-red-500/5', 'border-red-500/30');
            if (select && select.value) {
                row.classList.remove('bg-neutral-800/30', 'border-neutral-700/50');
                row.classList.add('bg-green-500/5', 'border-green-500/30');
            } else {
                row.classList.remove('bg-green-500/5', 'border-green-500/30');
                row.classList.add('bg-neutral-800/30', 'border-neutral-700/50');
            }
        }
    }
    checkValidation();
}

/**
 * Toggles the cancel state for an appointment.
 */
function toggleCancelAppointment(appId) {
    const btnCancel = document.getElementById(`bulk-reassign-cancel-${appId}`);
    const isCancelled = btnCancel.dataset.state === 'cancelled';
    updateRowActionState(appId, isCancelled ? 'reassign' : 'cancel');
}

window.toggleCancelAppointment = toggleCancelAppointment;
window.updateRowActionState = updateRowActionState;

/**
 * Validates if the confirm button should be enabled.
 */
function checkValidation() {
    const btnConfirm = document.getElementById('btn-confirm-reassign');
    if (!btnConfirm) return;
    
    let allValid = true;
    bulkReassignState.appointments.forEach(app => {
        const btnCancel = document.getElementById(`bulk-reassign-cancel-${app.id}`);
        if (btnCancel) {
            const isCancelled = btnCancel.dataset.state === 'cancelled';
            if (!isCancelled) {
                const select = document.getElementById(`bulk-reassign-select-${app.id}`);
                if (select && !select.value) {
                    allValid = false;
                }
            }
        }
    });

    btnConfirm.disabled = !allValid;
}
window.checkValidation = checkValidation;

/**
 * Cancels all future appointments in the list.
 */
function cancelAllFutureAppointments() {
    bulkReassignState.appointments.forEach(app => {
        updateRowActionState(app.id, 'cancel');
    });
}
window.cancelAllFutureAppointments = cancelAllFutureAppointments;

/**
 * Renders the list of appointments in the modal.
 */
function renderBulkReassignList() {
    const listDiv = document.getElementById('bulk-reassign-list');
    listDiv.innerHTML = '';

    if (bulkReassignState.appointments.length === 0) {
        listDiv.innerHTML = '<p class="text-sm text-neutral-400 p-4 text-center">No hay citas futuras.</p>';
        return;
    }

    bulkReassignState.appointments.forEach((app) => {
        // Find available barbers for this exact time block
        let availableOptions = '';
        let availableCount = 0;
        bulkReassignState.availableBarbers.forEach(b => {
            if (isBarberAvailable(b, app.start_time_iso, app.total_duration)) {
                availableOptions += `<option value="${b.id}">${b.name}</option>`;
                availableCount++;
            }
        });

        let selectHtml = '';
        if (availableCount > 0) {
            selectHtml = `
                <select id="bulk-reassign-select-${app.id}" onchange="updateRowActionState(${app.id}, 'reassign')" class="w-full px-3 py-2 bg-neutral-800 border border-neutral-700 rounded-lg text-white text-sm focus:ring-2 focus:ring-brand focus:border-brand transition-colors outline-none">
                    <option value="" disabled selected>Reasignar a...</option>
                    ${availableOptions}
                </select>
            `;
        } else {
            selectHtml = `
                <select id="bulk-reassign-select-${app.id}" disabled class="w-full px-3 py-2 bg-neutral-800 border border-neutral-700 rounded-lg text-neutral-500 text-sm opacity-70 outline-none">
                    <option value="" disabled selected>No hay barberos libres</option>
                </select>
            `;
        }

        const row = document.createElement('div');
        row.id = `bulk-row-${app.id}`;
        row.className = "p-4 bg-neutral-800/30 border border-neutral-700/50 rounded-xl flex items-center justify-between gap-4 transition-colors";
        row.innerHTML = `
            <div class="flex-1 grid grid-cols-12 gap-4 items-center">
                <!-- Info -->
                <div class="col-span-12 md:col-span-7">
                    <div class="flex items-center gap-3">
                        <div class="w-20 h-12 rounded-lg bg-neutral-800 border border-neutral-700 flex flex-col items-center justify-center shrink-0 p-1 shadow-sm">
                            <span class="text-[10px] text-neutral-400 font-medium uppercase mb-0.5 tracking-wide leading-none">${app.date.split('/')[0]}</span>
                            <span class="text-xs text-white font-bold whitespace-nowrap leading-none">${app.time}</span>
                        </div>
                        <div>
                            <p class="text-sm font-semibold text-white truncate max-w-[200px]" title="${app.client_name}">${app.client_name}</p>
                            <p class="text-xs text-neutral-400 truncate max-w-[250px]" title="${app.services}">${app.services} (${app.total_duration} min)</p>
                        </div>
                    </div>
                </div>
                
                <!-- Action -->
                <div class="col-span-12 md:col-span-5 flex items-center gap-2">
                    <div class="flex-1">
                        ${selectHtml}
                    </div>
                    <button type="button" id="bulk-reassign-cancel-${app.id}" onclick="toggleCancelAppointment(${app.id})" data-state="active" data-tooltip="Cancelar cita"
                            class="shrink-0 w-9 h-9 flex items-center justify-center rounded-lg border border-neutral-700 bg-neutral-800 text-neutral-500 hover:text-red-400 hover:border-red-500/30 transition-all">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
                    </button>
                </div>
            </div>
        `;
        listDiv.appendChild(row);

        // Auto-cancel if no barbers available
        if (availableCount === 0) {
            updateRowActionState(app.id, 'cancel');
        }
    });
    
    // Initial validation check
    checkValidation();
}

/**
 * Confirms and submits the bulk reassignment.
 */
async function confirmBulkReassign() {
    const reassignments = [];
    let hasError = false;

    bulkReassignState.appointments.forEach(app => {
        const btnCancel = document.getElementById(`bulk-reassign-cancel-${app.id}`);
        const isCancelled = btnCancel.dataset.state === 'cancelled';
        
        if (isCancelled) {
            reassignments.push({
                cita_id: app.id,
                accion: "cancelar"
            });
        } else {
            const select = document.getElementById(`bulk-reassign-select-${app.id}`);
            if (!select.value) {
                hasError = true;
                select.classList.add('border-red-500', 'ring-1', 'ring-red-500');
            } else {
                select.classList.remove('border-red-500', 'ring-1', 'ring-red-500');
                reassignments.push({
                    cita_id: app.id,
                    accion: "reasignar",
                    nuevo_barbero_id: parseInt(select.value)
                });
            }
        }
    });

    if (hasError) {
        if (typeof Toastify !== 'undefined') {
            Toastify({
                text: "Por favor, resuelve todas las citas (reasignar o cancelar).",
                duration: 3000,
                gravity: "top",
                position: "right",
                style: { background: "#ff2301", borderRadius: "8px", fontFamily: "Poppins, sans-serif", fontSize: "14px", fontWeight: "500" }
            }).showToast();
        } else if (typeof Swal !== 'undefined') {
            Swal.fire({
                title: 'Atención',
                text: 'Por favor, resuelve todas las citas.',
                icon: 'warning',
                background: '#1a1a1c',
                color: '#fff',
                confirmButtonColor: '#ff2301'
            });
        }
        return;
    }

    // Prepare payload
    const payload = {
        ...bulkReassignState.deactivatePayload,
        reassignments: reassignments
    };

    // UI Loading
    const loader = document.getElementById('bulk-loader');
    const btn = document.getElementById('btn-confirm-reassign');
    const btnText = btn.querySelector('span');
    const origText = btnText.textContent;
    
    loader.classList.remove('hidden');
    btn.disabled = true;
    btnText.textContent = 'Procesando...';

    try {
        const res = await fetch(bulkReassignState.deactivateEndpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': bulkReassignState.csrfToken
            },
            body: JSON.stringify(payload)
        });

        if (res.ok) {
            closeBulkReassignModal();
            if (bulkReassignState.onSuccessCallback) {
                bulkReassignState.onSuccessCallback();
            }
        } else {
            const data = await res.json();
            throw new Error(data.error || "Error al procesar la reasignación");
        }
    } catch (err) {
        console.error(err);
        if (typeof Toastify !== 'undefined') {
            Toastify({
                text: err.message || "Error de red",
                duration: 4000,
                gravity: "top",
                position: "right",
                style: { background: "#ff2301", borderRadius: "8px", fontFamily: "Poppins, sans-serif", fontSize: "14px", fontWeight: "500" }
            }).showToast();
        } else if (typeof Swal !== 'undefined') {
            Swal.fire({
                title: 'Error',
                text: err.message || 'Error de red',
                icon: 'error',
                background: '#1a1a1c',
                color: '#fff',
                confirmButtonColor: '#ff2301'
            });
        }
    } finally {
        loader.classList.add('hidden');
        btn.disabled = false;
        btnText.textContent = origText;
    }
}
window.confirmBulkReassign = confirmBulkReassign;
