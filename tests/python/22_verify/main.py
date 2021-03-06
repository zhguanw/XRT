import sys
import uuid
from xrt_binding import * # found in PYTHONPATH
sys.path.append('../') # utils_binding.py
from utils_binding import *

XHELLO_HELLO_CONTROL_ADDR_AP_CTRL = 0x00
XHELLO_HELLO_CONTROL_ADDR_GIE = 0x04
XHELLO_HELLO_CONTROL_ADDR_IER = 0x08
XHELLO_HELLO_CONTROL_ADDR_ISR = 0x0c
XHELLO_HELLO_CONTROL_ADDR_GROUP_ID_X_DATA = 0x10
XHELLO_HELLO_CONTROL_BITS_GROUP_ID_X_DATA = 32
XHELLO_HELLO_CONTROL_ADDR_GROUP_ID_Y_DATA = 0x18
XHELLO_HELLO_CONTROL_BITS_GROUP_ID_Y_DATA = 32
XHELLO_HELLO_CONTROL_ADDR_GROUP_ID_Z_DATA = 0x20
XHELLO_HELLO_CONTROL_BITS_GROUP_ID_Z_DATA = 32
XHELLO_HELLO_CONTROL_ADDR_GLOBAL_OFFSET_X_DATA = 0x28
XHELLO_HELLO_CONTROL_BITS_GLOBAL_OFFSET_X_DATA = 32
XHELLO_HELLO_CONTROL_ADDR_GLOBAL_OFFSET_Y_DATA = 0x30
XHELLO_HELLO_CONTROL_BITS_GLOBAL_OFFSET_Y_DATA = 32
XHELLO_HELLO_CONTROL_ADDR_GLOBAL_OFFSET_Z_DATA = 0x38
XHELLO_HELLO_CONTROL_BITS_GLOBAL_OFFSET_Z_DATA = 32
XHELLO_HELLO_CONTROL_ADDR_ACCESS1_DATA = 0x40
XHELLO_HELLO_CONTROL_BITS_ACCESS1_DATA = 64


def runKernel(opt):
    boHandle = xclAllocBO(opt.handle, opt.DATA_SIZE, xclBOKind.XCL_BO_DEVICE_RAM, opt.first_mem)
    bo = xclMapBO(opt.handle, boHandle, True)
    ctypes.memset(bo, 0, opt.DATA_SIZE)

    if xclSyncBO(opt.handle, boHandle, xclBOSyncDirection.XCL_BO_SYNC_BO_TO_DEVICE, opt.DATA_SIZE, 0):
        return 1

    print("Original string = [%s]\n") % bo.contents[:]

    p = xclBOProperties()
    bodevAddr = p.paddr if not (xclGetBOProperties(opt.handle, boHandle, p)) else -1

    if bodevAddr is -1:
        return 1

    # Allocate the exec_bo
    execHandle = xclAllocBO(opt.handle, opt.DATA_SIZE, xclBOKind.XCL_BO_SHARED_VIRTUAL, (1 << 31))
    execData = xclMapBO(opt.handle, execHandle, True)  # returns mmap()

    print("Construct the exe buf cmd to configure FPGA")

    ecmd = ert_configure_cmd.from_buffer(execData.contents)
    ecmd.m_uert.m_cmd_struct.state = 1  # ERT_CMD_STATE_NEW
    ecmd.m_uert.m_cmd_struct.opcode = 2  # ERT_CONFIGURE

    ecmd.slot_size = opt.DATA_SIZE
    ecmd.num_cus = 1
    ecmd.cu_shift = 16
    ecmd.cu_base_addr = opt.cu_base_addr

    ecmd.m_features.ert = opt.ert
    if opt.ert:
        ecmd.m_features.cu_dma = 1
        ecmd.m_features.cu_isr = 1

    # CU -> base address mapping
    ecmd.data[0] = opt.cu_base_addr
    ecmd.m_uert.m_cmd_struct.count = 5 + ecmd.num_cus

#    sz = sizeof(ert_configure_cmd)
    print("Send the exec command and configure FPGA (ERT)")

    # Send the command.
    ret = xclExecBuf(opt.handle, execHandle)

    if ret:
        print("Unable to issue xclExecBuf")
        return 1

    print("Wait until the command finish")

    while xclExecWait(opt.handle, 1000) == 0:
        print(".")

    if ecmd.m_uert.m_cmd_struct.state != 4:
        print("configure command failed")
        return 1

    print("Construct the exec command to run the kernel on FPGA")

    xclOpenContext(opt.handle, opt.xuuid, 0, True)
    # construct the exec buffer cmd to start the kernel
    start_cmd = ert_start_kernel_cmd.from_buffer(execData.contents)
    rsz = (XHELLO_HELLO_CONTROL_ADDR_ACCESS1_DATA / 4 + 1) + 1  # regmap array size
    ctypes.memset(execData.contents, 0, ctypes.sizeof(ert_start_kernel_cmd) + rsz*4)
    start_cmd.m_uert.m_start_cmd_struct.state = 1  # ERT_CMD_STATE_NEW
    start_cmd.m_uert.m_start_cmd_struct.opcode = 0  # ERT_START_CU
    start_cmd.m_uert.m_start_cmd_struct.count = 1 + rsz
    start_cmd.cu_mask = 0x1

    # Prepare kernel reg map
    new_data = (ctypes.c_uint32 * rsz).from_buffer(execData.contents, 8)
    new_data[XHELLO_HELLO_CONTROL_ADDR_AP_CTRL] = 0x0
    new_data[XHELLO_HELLO_CONTROL_ADDR_ACCESS1_DATA / 4] = bodevAddr
    new_data[XHELLO_HELLO_CONTROL_ADDR_ACCESS1_DATA / 4 + 1] = (bodevAddr >> 32) & 0xFFFFFFFF

    if xclExecBuf(opt.handle, execHandle):
        print("Unable to issue xclExecBuf")
        return 1
    else:
        print("Kernel start command issued through xclExecBuf : start_kernel")
        print("Now wait until the kernel finish")

    print("Wait until the command finish")

    while xclExecWait(opt.handle, 100) == 0:
        print(".")

    if start_cmd.m_uert.m_start_cmd_struct.state != 4:
        print("configure command failed")
        return 1

    # get the output xclSyncBO
    print("Get the output data from the device")
    if xclSyncBO(opt.handle, boHandle, xclBOSyncDirection.XCL_BO_SYNC_BO_FROM_DEVICE, opt.DATA_SIZE, 0):
        return 1

    result = bo.contents[:len("Hello World")]
    print("Result string = [%s]\n") % result

    xclCloseContext(opt.handle, opt.xuuid, 0)
    xclFreeBO(opt.handle, execHandle)
    xclFreeBO(opt.handle, boHandle)

    if result != "Hello World":
        return 1
    else:
        return 0


def main(args):
    opt = Options()
    Options.getOptions(opt, args)

    try:
        if initXRT(opt):
            xclClose(opt.handle)
            return 1
        if opt.first_mem < 0:
            xclClose(opt.handle)
            return 1
        if runKernel(opt):
            xclClose(opt.handle)
            return 1

    except Exception as exp:
        print("Exception: ")
        print(exp)  # prints the err
        print("FAILED TEST")
        sys.exit()

    print("PASSED TEST")


if __name__ == "__main__":
    main(sys.argv)
