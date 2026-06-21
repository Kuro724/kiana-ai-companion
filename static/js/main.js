import * as THREE from '/static/js/libs/three.module.js';
import { GLTFLoader } from '/static/js/libs/GLTFLoader.js';
import { VRMLoaderPlugin } from '/static/js/libs/three-vrm.module.js';

document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const chatInput = document.getElementById("chat-input");
    const sendBtn = document.getElementById("send-btn");
    const voiceBtn = document.getElementById("voice-btn");
    const messagesContainer = document.getElementById("messages-container");
    const familiarityScore = document.getElementById("familiarity-score");
    const interactionCount = document.getElementById("interaction-count");
    const emotionTag = document.getElementById("kiana-emotion-tag");
    const emotionGlow = document.getElementById("emotion-glow");
    const kianaStatus = document.getElementById("kiana-current-status");
    const memoriesContainer = document.getElementById("memories-container");
    const ttsToggle = document.getElementById("tts-toggle");
    const toggleSidebarBtn = document.getElementById("toggle-sidebar-btn");
    const sidebar = document.querySelector(".sidebar-panel");
    const resetBtn = document.getElementById("reset-btn");
    
    // VRM Model Upload Elements
    const fileInput = document.getElementById("vrm-file-input");
    const uploadBtn = document.getElementById("upload-vrm-btn");
    const vrmStatusText = document.getElementById("vrm-upload-status");
    
    // Application State
    let isAutoTTS = true;
    let isRecording = false;
    let mediaRecorder = null;
    let audioChunks = [];
    let audioPlayer = new Audio();
    
    // 3D VRM Rendering Engine State
    let currentVrm = null;
    let clock = new THREE.Clock();
    let scene, camera, renderer;
    let isSpeakingState = false;
    
    // Adjust textarea height automatically
    chatInput.addEventListener("input", () => {
        chatInput.style.height = "auto";
        chatInput.style.height = (chatInput.scrollHeight - 6) + "px";
    });

    // 1. Initial configuration & status load
    function loadStatus() {
        fetch("/api/status")
            .then(res => res.json())
            .then(data => {
                familiarityScore.textContent = data.familiarity;
                interactionCount.textContent = data.interaction_count;
                updateEmotion(data.current_emotion);
                updateMemories(data.memories);
                
                // Add initial greeting if history is empty
                fetch("/api/history")
                    .then(res => res.json())
                    .then(history => {
                        messagesContainer.innerHTML = "";
                        if (history.length === 0) {
                            addMessage("kiana", data.greeting);
                            if (isAutoTTS) speakText(data.greeting);
                        } else {
                            history.forEach(msg => {
                                addMessage(msg.sender === "User" ? "user" : "kiana", msg.message);
                            });
                            scrollToBottom();
                        }
                    });
            })
            .catch(err => console.error("Error loading status:", err));
    }

    // 2. Add message bubble
    function addMessage(sender, text) {
        const bubble = document.createElement("div");
        bubble.classList.add("message-bubble", sender);
        bubble.textContent = text;
        messagesContainer.appendChild(bubble);
        scrollToBottom();
    }

    function scrollToBottom() {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    // 3. Update Emotional State Visuals & 3D Avatar Expression
    function updateEmotion(emotion) {
        // Update tags
        emotionTag.className = ""; // clear
        emotionTag.classList.add(`emotion-${emotion.toLowerCase()}`);
        emotionTag.textContent = emotion;
        
        // Update glow ring
        emotionGlow.className = "emotion-glow"; // clear
        emotionGlow.classList.add(`glow-${emotion.toLowerCase()}`);

        // Update 3D Face Expression
        applyAvatarExpression(emotion);
    }

    function applyAvatarExpression(emotion) {
        if (!currentVrm) return;
        const manager = currentVrm.expressionManager;
        ['happy','angry','sad','relaxed','surprised','neutral'].forEach(k => {
            try { manager.setValue(k, 0.0); } catch(e) {}
        });

        if (emotion === 'Happy') {
            manager.setValue('happy', 1.0);
        } else if (emotion === 'Excited') {
            manager.setValue('happy', 0.7);
            manager.setValue('surprised', 0.4);
        } else if (emotion === 'Concerned') {
            manager.setValue('sad', 0.8);
        } else if (emotion === 'Curious') {
            manager.setValue('surprised', 0.7);
        } else if (emotion === 'Sleepy') {
            manager.setValue('relaxed', 0.4);
            manager.setValue('blink', 0.3);
        } else if (emotion === 'Surprised') {
            manager.setValue('surprised', 1.0);
        } else if (emotion === 'Embarrassed') {
            manager.setValue('happy', 0.3);
            manager.setValue('relaxed', 0.3);
        } else if (emotion === 'Proud') {
            manager.setValue('happy', 0.7);
            manager.setValue('relaxed', 0.3);
        } else if (emotion === 'Thinking') {
            if (currentVrm.humanoid) {
                const neck = currentVrm.humanoid.getNormalizedBoneNode('neck');
                if (neck) neck.rotation.z = -0.1;
            }
        } else {
            manager.setValue('relaxed', 1.0);
        }
    }

    // Talking Animation toggle (Viseme Lip Sync)
    function startMouthMovement() {
        isSpeakingState = true;
    }

    function stopMouthMovement() {
        isSpeakingState = false;
    }

    // 3D VRM Initialization
    function init3D() {
        const canvas = document.getElementById("vrm-canvas");
        const container = document.getElementById("kiana-avatar-3d");
        if (!canvas || !container) return;
        
        const width = container.clientWidth || 130;
        const height = container.clientHeight || 130;
        
        // Create Scene
        scene = new THREE.Scene();
        
        // Setup Camera focused on character face
        camera = new THREE.PerspectiveCamera(30, width / height, 0.1, 20.0);
        camera.position.set(0.0, 1.45, 1.05); // Focused on upper body / head
        camera.lookAt(0.0, 1.45, 0.0);
        
        // WebGL Renderer
        renderer = new THREE.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true });
        renderer.setSize(width, height);
        renderer.setPixelRatio(window.devicePixelRatio);
        
        // Lights
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
        scene.add(ambientLight);
        
        const directionalLight = new THREE.DirectionalLight(0xffffff, 0.5);
        directionalLight.position.set(1.0, 1.0, 1.0).normalize();
        scene.add(directionalLight);
        
        // Load default or uploaded custom model
        loadVRMModel("/static/assets/kiana.vrm");
        
        // Start Render Loop
        animate3D();
    }

    function loadVRMModel(url) {
        if (currentVrm) {
            scene.remove(currentVrm.scene);
            currentVrm = null;
        }
        
        vrmStatusText.textContent = "Loading VRM Model...";
        
        const loader = new GLTFLoader();
        loader.register((parser) => new VRMLoaderPlugin(parser));
        
        loader.load(
            url,
            (gltf) => {
                const vrm = gltf.userData.vrm;
                scene.add(vrm.scene);
                currentVrm = vrm;
                
                // Align model facing the camera
                vrm.scene.rotation.y = Math.PI;
                
                // Hide helper meshes if any
                vrm.scene.traverse((obj) => {
                    obj.frustumCulled = false;
                });
                
                if (url.includes("kiana.vrm")) {
                    vrmStatusText.textContent = "Custom VRM Active";
                } else {
                    vrmStatusText.textContent = "Using Default Model";
                }
                
                // Apply current expression frame
                applyAvatarExpression(emotionTag.textContent);
            },
            (progress) => {},
            (error) => {
                // Fallback to public Pixiv three-vrm sample model
                const defaultModelUrl = "https://pixiv.github.io/three-vrm/packages/three-vrm/examples/models/VRM1_Self_introduction_1_1.vrm";
                if (url !== defaultModelUrl) {
                    console.log("Failed to load local kiana.vrm. Loading default public model...");
                    loadVRMModel(defaultModelUrl);
                } else {
                    console.error("VRM loader failed entirely:", error);
                    vrmStatusText.textContent = "Failed to load model";
                }
            }
        );
    }

    function animate3D() {
        requestAnimationFrame(animate3D);
        const delta = clock.getDelta();
        
        if (currentVrm) {
            const time = clock.getElapsedTime();
            
            // 1. Idle breathing: rotate chest and spine bones
            const spine = currentVrm.humanoid.getNormalizedBoneNode('spine');
            if (spine) {
                spine.rotation.z = Math.sin(time * 2.0) * 0.012;
                spine.rotation.x = Math.sin(time * 1.5) * 0.008;
            }
            
            // 2. Eyes Blinking: every 4.5 seconds
            const blinkFactor = Math.sin(time * 0.5) > 0.985 ? 1.0 : 0.0;
            if (blinkFactor > 0) {
                currentVrm.expressionManager.setValue('blink', blinkFactor);
            } else {
                // Restore sleepy partial blink if active
                if (emotionTag.textContent === "Sleepy") {
                    currentVrm.expressionManager.setValue('blink', 0.3);
                } else {
                    currentVrm.expressionManager.setValue('blink', 0.0);
                }
            }
            
            // 3. Dynamic Lip Sync / Mouth Talking Viseme
            if (isSpeakingState) {
                const mouthOpen = 0.2 + Math.abs(Math.sin(time * 18.0)) * 0.8;
                currentVrm.expressionManager.setValue('aa', mouthOpen);
            } else {
                currentVrm.expressionManager.setValue('aa', 0.0);
            }
            
            currentVrm.update(delta);
        }
        
        renderer.render(scene, camera);
    }



    // 4. Update Memories List
    function updateMemories(memories) {
        memoriesContainer.innerHTML = "";
        const keys = Object.keys(memories);
        
        if (keys.length === 0) {
            memoriesContainer.innerHTML = '<div class="empty-memories">No memories stored yet. Let me get to know you!</div>';
            return;
        }
        
        keys.forEach(key => {
            const item = document.createElement("div");
            item.classList.add("memory-tag");
            
            const keyLabel = document.createElement("div");
            keyLabel.classList.add("memory-key");
            // Capitalize and replace underscores
            keyLabel.textContent = key.replace(/_/g, " ").toUpperCase();
            
            const valLabel = document.createElement("div");
            valLabel.classList.add("memory-value");
            valLabel.textContent = memories[key];
            
            item.appendChild(keyLabel);
            item.appendChild(valLabel);
            memoriesContainer.appendChild(item);
        });
    }

    // 5. Send message logic
    function sendMessage() {
        const text = chatInput.value.strip ? chatInput.value.strip() : chatInput.value.trim();
        if (!text) return;
        
        // Clear input and restore height
        chatInput.value = "";
        chatInput.style.height = "auto";
        
        // Append user bubble
        addMessage("user", text);
        
        // Set state to thinking
        kianaStatus.textContent = "Thinking...";
        kianaStatus.classList.add("speaking");
        
        fetch("/api/chat", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ message: text })
        })
        .then(res => res.json())
        .then(data => {
            kianaStatus.textContent = "Listening for you...";
            kianaStatus.classList.remove("speaking");
            
            // Add Kiana's reply
            addMessage("kiana", data.response);
            updateEmotion(data.emotion);
            updateMemories(data.memories);
            familiarityScore.textContent = data.familiarity;
            
            // Increment local interaction counter
            interactionCount.textContent = parseInt(interactionCount.textContent) + 1;
            
            // Voice Output
            if (isAutoTTS) {
                speakText(data.response);
            }
        })
        .catch(err => {
            console.error("Chat error:", err);
            kianaStatus.textContent = "Listening for you...";
            kianaStatus.classList.remove("speaking");
            addMessage("kiana", "I had a bit of trouble connecting to my thoughts just now. Could you try saying that again?");
        });
    }

    // 6. Voice Text-to-Speech player
    function speakText(text) {
        kianaStatus.textContent = "Speaking...";
        kianaStatus.classList.add("speaking");
        
        fetch("/api/voice-tts", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ text: text })
        })
        .then(res => res.json())
        .then(data => {
            if (data.audio_url) {
                audioPlayer.src = data.audio_url;
                audioPlayer.play()
                    .then(() => {
                        startMouthMovement();
                    })
                    .catch(e => console.log("Audio play deferred or blocked:", e));
                
                audioPlayer.onended = () => {
                    stopMouthMovement();
                    kianaStatus.textContent = "Listening for you...";
                    kianaStatus.classList.remove("speaking");
                };
            } else {
                kianaStatus.textContent = "Listening for you...";
                kianaStatus.classList.remove("speaking");
            }
        })
        .catch(err => {
            console.error("TTS error:", err);
            kianaStatus.textContent = "Listening for you...";
            kianaStatus.classList.remove("speaking");
        });
    }


    // 7. Speech-to-Text Microphone logic
    // We will attempt Web Speech API first (highly accurate, runs instantly client side)
    // If not supported, we fall back to MediaRecorder file upload.
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    let recognition = null;
    
    if (SpeechRecognition) {
        recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.lang = "en-US";
        
        recognition.onstart = () => {
            isRecording = true;
            voiceBtn.classList.add("recording");
            kianaStatus.textContent = "Listening to you...";
            kianaStatus.classList.add("listening");
        };
        
        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            chatInput.value = transcript;
            // auto-trigger height adjust
            chatInput.dispatchEvent(new Event("input"));
        };
        
        recognition.onerror = (e) => {
            console.error("Speech recognition error:", e);
        };
        
        recognition.onend = () => {
            isRecording = false;
            voiceBtn.classList.remove("recording");
            kianaStatus.textContent = "Listening for you...";
            kianaStatus.classList.remove("listening");
        };
    }

    function toggleRecording() {
        if (recognition) {
            // Browser speech API path
            if (isRecording) {
                recognition.stop();
            } else {
                recognition.start();
            }
        } else {
            // MediaRecorder API path (local audio file synthesis fallback)
            if (isRecording) {
                stopMediaRecording();
            } else {
                startMediaRecording();
            }
        }
    }

    function startMediaRecording() {
        navigator.mediaDevices.getUserMedia({ audio: true })
            .then(stream => {
                isRecording = true;
                voiceBtn.classList.add("recording");
                kianaStatus.textContent = "Recording...";
                kianaStatus.classList.add("listening");
                
                audioChunks = [];
                mediaRecorder = new MediaRecorder(stream);
                mediaRecorder.ondataavailable = event => {
                    audioChunks.push(event.data);
                };
                
                mediaRecorder.onstop = () => {
                    const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                    uploadAudio(audioBlob);
                    
                    // Stop all audio tracks to release the mic
                    stream.getTracks().forEach(track => track.stop());
                };
                
                mediaRecorder.start();
            })
            .catch(err => {
                console.error("Mic access denied:", err);
                alert("Could not access your microphone. Please check permissions!");
            });
    }

    function stopMediaRecording() {
        if (mediaRecorder && mediaRecorder.state !== "inactive") {
            mediaRecorder.stop();
        }
        isRecording = false;
        voiceBtn.classList.remove("recording");
        kianaStatus.textContent = "Listening for you...";
        kianaStatus.classList.remove("listening");
    }

    function uploadAudio(blob) {
        const formData = new FormData();
        formData.append("audio", blob, "audio.wav");
        
        kianaStatus.textContent = "Transcribing...";
        
        fetch("/api/voice-stt", {
            method: "POST",
            body: formData
        })
        .then(res => res.json())
        .then(data => {
            kianaStatus.textContent = "Listening for you...";
            if (data.text) {
                chatInput.value = data.text;
                chatInput.dispatchEvent(new Event("input"));
            }
        })
        .catch(err => {
            console.error("Upload transcription error:", err);
            kianaStatus.textContent = "Listening for you...";
        });
    }

    // Event Listeners
    sendBtn.addEventListener("click", sendMessage);
    
    chatInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    voiceBtn.addEventListener("click", toggleRecording);

    ttsToggle.addEventListener("click", () => {
        isAutoTTS = !isAutoTTS;
        ttsToggle.classList.toggle("active", isAutoTTS);
        if (!isAutoTTS) {
            audioPlayer.pause();
            stopMouthMovement();
            kianaStatus.textContent = "Listening for you...";
            kianaStatus.classList.remove("speaking");
        }
    });

    toggleSidebarBtn.addEventListener("click", () => {
        sidebar.classList.toggle("collapsed");
    });

    resetBtn.addEventListener("click", () => {
        if (confirm("Are you sure you want to reset Kiana's memory and chat history? This cannot be undone.")) {
            fetch("/api/reset", { method: "POST" })
                .then(res => res.json())
                .then(data => {
                    alert(data.message);
                    loadStatus();
                })
                .catch(err => console.error("Error resetting companion:", err));
        }
    });

    // Start status load & 3D Initialization
    ttsToggle.classList.toggle("active", isAutoTTS);
    loadStatus();
    init3D();

    // VRM file selection and upload
    if (uploadBtn && fileInput) {
        uploadBtn.addEventListener("click", () => fileInput.click());
        fileInput.addEventListener("change", (e) => {
            const file = e.target.files[0];
            if (!file) return;
            
            const formData = new FormData();
            formData.append("file", file);
            
            vrmStatusText.textContent = "Uploading Model...";
            
            fetch("/api/upload-vrm", {
                method: "POST",
                body: formData
            })
            .then(res => res.json())
            .then(data => {
                if (data.status === "success") {
                    vrmStatusText.textContent = "Uploaded! Loading...";
                    loadVRMModel("/static/assets/kiana.vrm");
                } else {
                    vrmStatusText.textContent = "Upload failed";
                    alert(data.error || "Failed to upload model.");
                }
            })
            .catch(err => {
                console.error("VRM Upload error:", err);
                vrmStatusText.textContent = "Upload failed";
            });
        });
    }
});
