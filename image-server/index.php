<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="color-scheme" content="light dark">
    <title>Image Generator</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <div id="root">
        <main class="container">
            <div class="header">
                <h1>AI Image Generator</h1>
                <p>Generate images using Google Gemini AI</p>
            </div>

            <!-- Form View -->
            <div id="form-view" class="form">
                <div class="field-group">
                    <label class="label" for="prompt-input">Prompt</label>
                    <textarea
                        id="prompt-input"
                        class="prompt-input"
                        placeholder="Describe the image you want to generate..."
                        rows="3"
                    ></textarea>
                </div>

                <div class="field-group">
                    <label class="label" for="aspect-ratio">Aspect Ratio</label>
                    <select id="aspect-ratio" class="select">
                        <!-- Options populated by JavaScript -->
                    </select>
                </div>

                <button id="generate-button" class="generate-button" disabled>
                    Generate Image
                </button>
            </div>

            <!-- Generating View -->
            <div id="generating-view" class="image-container hidden">
                <div class="loading">
                    <div class="spinner"></div>
                    <span>Generating image...</span>
                </div>
            </div>

            <!-- Completed View -->
            <div id="completed-view" class="image-with-actions hidden">
                <img
                    id="generated-image"
                    src=""
                    alt="Generated image"
                    class="generated-image"
                >
                <div class="button-group">
                    <button id="download-button" class="download-button">
                        Download Image
                    </button>
                    <button class="reset-button">
                        Generate Another
                    </button>
                </div>
            </div>

            <!-- Error View -->
            <div id="error-view" class="image-container hidden">
                <div class="error">
                    <strong>Error:</strong> <span id="error-message"></span>
                </div>
                <button class="reset-button">
                    Try Again
                </button>
            </div>
        </main>
    </div>

    <script src="script.js"></script>
</body>
</html>
