/**
 * Image Generator - Client-side JavaScript
 */

// Supported aspect ratios
const ASPECT_RATIOS = [
    { value: '1:1', label: '1:1 (Square)' },
    { value: '16:9', label: '16:9 (Widescreen)' },
    { value: '9:16', label: '9:16 (Portrait)' },
    { value: '4:3', label: '4:3 (Standard)' },
    { value: '3:4', label: '3:4 (Portrait)' },
    { value: '3:2', label: '3:2 (Photo)' },
    { value: '2:3', label: '2:3 (Portrait Photo)' },
    { value: '21:9', label: '21:9 (Ultrawide)' },
    { value: '5:4', label: '5:4' },
    { value: '4:5', label: '4:5' },
];

// Application state
let appState = 'form';
let generatedImage = null;

// DOM elements
const formView = document.getElementById('form-view');
const generatingView = document.getElementById('generating-view');
const completedView = document.getElementById('completed-view');
const errorView = document.getElementById('error-view');

const promptInput = document.getElementById('prompt-input');
const aspectRatioSelect = document.getElementById('aspect-ratio');
const generateButton = document.getElementById('generate-button');
const downloadButton = document.getElementById('download-button');
const resetButtons = document.querySelectorAll('.reset-button');
const generatedImageEl = document.getElementById('generated-image');
const errorMessageEl = document.getElementById('error-message');

/**
 * Initialize the application
 */
function init() {
    // Populate aspect ratio options
    ASPECT_RATIOS.forEach(ar => {
        const option = document.createElement('option');
        option.value = ar.value;
        option.textContent = ar.label;
        aspectRatioSelect.appendChild(option);
    });

    // Event listeners
    generateButton.addEventListener('click', handleGenerate);
    downloadButton.addEventListener('click', handleDownload);
    resetButtons.forEach(btn => btn.addEventListener('click', handleReset));

    // Enable/disable generate button based on prompt
    promptInput.addEventListener('input', () => {
        generateButton.disabled = !promptInput.value.trim();
    });

    // Initialize button state
    generateButton.disabled = true;

    updateView();
}

/**
 * Update the view based on current state
 */
function updateView() {
    formView.classList.toggle('hidden', appState !== 'form');
    generatingView.classList.toggle('hidden', appState !== 'generating');
    completedView.classList.toggle('hidden', appState !== 'completed');
    errorView.classList.toggle('hidden', appState !== 'error');
}

/**
 * Handle generate button click
 */
async function handleGenerate() {
    const prompt = promptInput.value.trim();
    if (!prompt) {
        showError('Please enter a prompt');
        return;
    }

    appState = 'generating';
    updateView();

    try {
        const response = await fetch('api.php', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                prompt: prompt,
                aspectRatio: aspectRatioSelect.value,
                generate: true
            })
        });

        const result = await response.json();
        console.log('Generation result:', result);

        if (result.status === 'completed' && result.imageBase64 && result.mimeType) {
            generatedImage = {
                base64: result.imageBase64,
                mimeType: result.mimeType
            };
            generatedImageEl.src = `data:${result.mimeType};base64,${result.imageBase64}`;
            appState = 'completed';
        } else if (result.status === 'error') {
            showError(result.error || 'Unknown error occurred');
        } else {
            showError('Unexpected response from server');
        }
    } catch (e) {
        console.error('Generation error:', e);
        showError(e.message || 'Failed to generate image');
    }

    updateView();
}

/**
 * Show error message
 */
function showError(message) {
    errorMessageEl.textContent = message;
    appState = 'error';
}

/**
 * Handle reset button click
 */
function handleReset() {
    appState = 'form';
    generatedImage = null;
    generatedImageEl.src = '';
    errorMessageEl.textContent = '';
    updateView();
}

/**
 * Handle download button click
 */
async function handleDownload() {
    if (!generatedImage) return;

    // Convert base64 to blob
    const byteCharacters = atob(generatedImage.base64);
    const byteNumbers = new Array(byteCharacters.length);
    for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i);
    }
    const byteArray = new Uint8Array(byteNumbers);
    const blob = new Blob([byteArray], { type: generatedImage.mimeType });
    const extension = generatedImage.mimeType.split('/')[1] || 'png';

    // Try File System Access API first (works in modern browsers)
    if ('showSaveFilePicker' in window) {
        try {
            const handle = await window.showSaveFilePicker({
                suggestedName: `generated-image-${Date.now()}.${extension}`,
                types: [
                    {
                        description: 'Image file',
                        accept: { [generatedImage.mimeType]: [`.${extension}`] },
                    },
                ],
            });
            const writable = await handle.createWritable();
            await writable.write(blob);
            await writable.close();
            return;
        } catch (e) {
            // User cancelled or API not supported, fall through to fallback
            if (e.name === 'AbortError') return;
        }
    }

    // Fallback: create download link
    const blobUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = `generated-image-${Date.now()}.${extension}`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(blobUrl);
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', init);
