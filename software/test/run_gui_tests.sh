#!/bin/bash
# GUI Test Runner for HaasoscopeProQt
# This script makes it easy to run various GUI tests on Linux/Mac
# Run from the test directory

echo ""
echo "================================================================================"
echo " HaasoscopeProQt GUI Test Runner"
echo "================================================================================"
echo ""

show_menu() {
    echo "Please select a test to run:"
    echo ""
    echo "  1. Quick Demo (simple 8-second test with screenshot)"
    echo "  2. Standalone Test (basic smoke test)"
    echo "  3. Create Baseline Screenshots"
    echo "  4. Run Automated Tests (compare to baseline)"
    echo "  5. Run pytest Suite (comprehensive tests)"
    echo "  6. Install Test Dependencies"
    echo "  7. Exit"
    echo ""
}

while true; do
    show_menu
    read -p "Enter your choice (1-7): " choice

    case $choice in
        1)
            echo ""
            echo "Running Quick Demo Test..."
            echo ""
            python3 demo_gui_test.py
            read -p "Press Enter to continue..."
            ;;
        2)
            echo ""
            echo "Running Standalone Test..."
            echo ""
            python3 test_gui_standalone.py --duration 10
            read -p "Press Enter to continue..."
            ;;
        3)
            echo ""
            echo "Creating Baseline Screenshots..."
            echo ""
            python3 test_gui_automated.py --baseline --verbose
            read -p "Press Enter to continue..."
            ;;
        4)
            echo ""
            echo "Running Automated Tests (comparing to baseline)..."
            echo ""
            python3 test_gui_automated.py --verbose
            read -p "Press Enter to continue..."
            ;;
        5)
            echo ""
            echo "Running pytest Test Suite..."
            echo ""
            pytest test_gui.py -v
            read -p "Press Enter to continue..."
            ;;
        6)
            echo ""
            echo "Installing Test Dependencies..."
            echo ""
            pip3 install -r test_requirements.txt
            echo ""
            echo "Installation complete!"
            read -p "Press Enter to continue..."
            ;;
        7)
            echo ""
            echo "Exiting..."
            echo ""
            exit 0
            ;;
        *)
            echo ""
            echo "Invalid choice. Please try again."
            echo ""
            ;;
    esac
done
