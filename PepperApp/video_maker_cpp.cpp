#include <pybind11/pybind11.h>
#include <pybind11/stl.h> // For std::vector, std::string
#include <pybind11/pytypes.h> // For py::list, py::bytes

#include <opencv2/opencv.hpp> // Main OpenCV header
#include <iostream>

namespace py = pybind11;

/**
 * @brief Creates a video file from a list of JPEG/PNG image buffers.
 * * This is the high-performance core. It decodes, resizes, and writes
 * frames using OpenCV's C++ API.
 * * @param frames A Python list of byte-strings (py::list of py::bytes).
 * @param video_path The output file path (e.g., "output.mp4").
 * @param fps The frames per second for the output video.
 * @param width The target width (e.g., 640).
 * @param height The target height (e.g., 480).
 * * @return The final video_path, or an empty string on failure.
 */
std::string create_video_core(py::list py_frames, std::string video_path, double fps, int width, int height) {
    cv::Size frame_size(width, height);
    int fourcc = cv::VideoWriter::fourcc('m', 'p', '4', 'v');

    cv::VideoWriter out;
    out.open(video_path, fourcc, fps, frame_size, true);

    if (!out.isOpened()) {
        std::cerr << "Error: Could not open video writer for: " << video_path << std::endl;
        return ""; // Return empty string to signal failure
    }

    int frame_idx = 0;
    for (py::handle frame_obj : py_frames) {
        // 1. Get bytes from Python
        std::string frame_data_str = frame_obj.cast<py::bytes>();
        
        // Skip empty buffers
        if (frame_data_str.empty() || frame_data_str.length() < 16) {
            std::cout << "Skipping C++ frame " << frame_idx << ": empty or too small buffer" << std::endl;
            frame_idx++;
            continue;
        }

        // 2. Convert to cv::Mat format for imdecode
        // We do a "copy-less" view of the string data
        std::vector<char> frame_data_vec(frame_data_str.begin(), frame_data_str.end());
        cv::Mat raw_data(frame_data_vec);
        cv::Mat image;

        try {
            // 3. Decode image
            image = cv::imdecode(raw_data, cv::IMREAD_COLOR);
        } catch (const cv::Exception& e) {
            std::cerr << "Skipping C++ frame " << frame_idx << ": imdecode error: " << e.what() << std::endl;
            frame_idx++;
            continue;
        }

        if (image.empty()) {
            std::cout << "Skipping C++ frame " << frame_idx << ": decode returned None" << std::endl;
            frame_idx++;
            continue;
        }

        // 4. Ensure 3 channels
        if (image.channels() == 1) {
            cv::cvtColor(image, image, cv::COLOR_GRAY2BGR);
        }

        // 5. Ensure size is consistent
        if (image.size() != frame_size) {
            cv::resize(image, image, frame_size);
        }

        // 6. Write frame
        out.write(image);
        frame_idx++;
    }

    out.release();
    std::cout << "C++ Core: Wrote " << (frame_idx) << " frames to " << video_path << std::endl;
    return video_path;
}

// This is the "magic" that creates the Python module
// The first argument "video_maker_cpp" MUST match the module name in setup.py
PYBIND11_MODULE(video_maker_cpp, m) {
    m.doc() = "High-performance video creation module"; // Optional module docstring
    
    // This exposes our C++ function to Python
    m.def("create_video_core", &create_video_core, "Creates a video from a list of image bytes",
          py::arg("frames"), 
          py::arg("video_path"), 
          py::arg("fps"), 
          py::arg("width"), 
          py::arg("height"));
}