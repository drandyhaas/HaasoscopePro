Haasoscope Pro - Code Architecture

This diagram provides a detailed view of the software architecture, showing key methods, data flows, and component responsibilities.

```mermaid
graph TD
    %% --- Styling Definitions ---
    classDef core fill:#d9ead3,stroke:#38761d,stroke-width:2px,font-size:14px;
    classDef startup fill:#cfe2f3,stroke:#3d85c6,stroke-width:2px,font-size:14px;
    classDef hardware fill:#fce5cd,stroke:#e69138,stroke-width:2px,font-size:14px;
    classDef helpers fill:#fff2cc,stroke:#f1c232,stroke-width:2px,font-size:14px;
    classDef datastore fill:#e2d0f3,stroke:#674ea7,stroke-width:2px,font-size:14px,shape:cylinder;
    classDef user fill:#f4cccc,stroke:#cc0000,stroke-width:2px,font-size:14px;
    classDef device fill:#d0e0e3,stroke:#45818e,stroke-width:2px,font-size:16px;

    %% --- Main Application Flow ---
    subgraph " "
        direction LR
        A["HaasoscopeProQt.py <br> <i>Entry Point</i>"] --> B{"main_window.py <br> <b>MainWindow (Controller)</b> <br> - Handles UI Events <br> - Orchestrates Data Flow <br> - Manages All Components"};
        User_Input(["User <br> Clicks, Menus, Keys"]) -.-> B;
    end

    subgraph "Central State (Model)"
        C[("scope_state.py <br> <b>ScopeState</b> <br> gain, offset, timebase, <br> isrolling, xy_mode, etc.")]
    end

    subgraph "Core Components"
        B -- "Writes Settings" --> C;
        C -- "Reads State" --> D;
        C -- "Reads State" --> E;
        C -- "Reads State" --> F;

        D{"hardware_controller.py <br> <b>HardwareController</b> <br> - get_event() <br> - set_gain() <br> - tell_downsample()"}
        E{"data_processor.py <br> <b>DataProcessor</b> <br> - process_board_data() <br> - calculate_fft() <br> - calculate_measurements()"}
        F{"plot_manager.py <br> <b>PlotManager (View)</b> <br> - update_plots() <br> - toggle_xy_view() <br> - set_reference_waveform()"}
    end
    
    B -- "Owns & Manages" --> D & E & F

    subgraph "Data & Command Flow"
        direction TB
        B -- "get_event()" --> D;
        D -- "Raw Data Packet" --> B;
        B -- "process_board_data(raw)" --> E;
        E -- "Clean `xydata`" --> B;
        B -- "update_plots(xydata)" --> F;
    end

    subgraph "Hardware Abstraction"
        direction TB
        D -- "Sends Low-Level <br> Commands (SPI, USB)" --> I["Low-Level Libs <br> usbs.py, board.py"];
        I -- "Receives Raw Bytes" --> D
        I -- "Interfaces With" --> J([<br><b>Physical Oscilloscope</b>]);
    end

    subgraph "UI Helpers"
        G["FFTWindow.py"]
        H["data_recorder.py"]
        B -. "Sends FFT Data" .-> G;
        B -. "Sends Waveform Data" .-> H;
    end

    %% --- Style Applications ---
    class A startup;
    class B,D,E,F core;
    class C datastore;
    class G,H helpers;
    class I,J hardware;
    class User_Input user;
    class J device;


