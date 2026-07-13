// Reusable, parameterized replacement for the many one-off "force-disassemble
// this address range and print it" scripts this project kept rewriting by
// hand (NHL95DumpVblank, NHL95DumpFrameHandler, NHL95DumpA3E6, NHL95DumpA55A,
// NHL95DumpReadSubs[23], NHL95DumpBeforeD6A, NHL95DumpD62, ... -- same body,
// different constants, every time).
//
// Usage (see CLAUDE.md's Ghidra section for the full analyzeHeadless
// invocation): pass START and END as ROM hex addresses, plus optional extra
// SEED addresses (space-separated) to also disassemble-from, all merged into
// one combined listing -- this is what NHL95DumpReadSubs3.java needed by
// hand to get a clean linear dump when a range contains multiple entry
// points reached only by internal branches, not fallthrough.
//
//   analyzeHeadless <projectDir> <projectName> -process "<rom>" -noanalysis \
//     -postScript DumpRange.java 0x9FCC8 0x9FD62 0x9FCCC \
//     -scriptPath tools/ghidra
//
// (First two positional args are START/END; any further args are extra
// seeds. If you only have one START and want the disassembler to also
// naturally fall through from it, omit the extra seeds.)
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.disassemble.Disassembler;

import java.util.ArrayList;
import java.util.List;

public class DumpRange extends GhidraScript {
    @Override
    public void run() throws Exception {
        List<String> args = new ArrayList<>();
        String[] scriptArgs = getScriptArgs();
        for (String a : scriptArgs) {
            args.add(a);
        }
        if (args.size() < 2) {
            println("Usage: DumpRange.java START END [SEED...]");
            println("  e.g. DumpRange.java 0x9FCC8 0x9FD62");
            return;
        }

        long start = Long.decode(args.get(0));
        long end = Long.decode(args.get(1));
        List<Long> seeds = new ArrayList<>();
        seeds.add(start);
        for (int i = 2; i < args.size(); i++) {
            seeds.add(Long.decode(args.get(i)));
        }

        AddressSpace space = currentProgram.getAddressFactory().getDefaultAddressSpace();
        Listing listing = currentProgram.getListing();
        Address startAddr = space.getAddress(start);
        Address endAddr = space.getAddress(end);
        AddressSet set = new AddressSet(startAddr, endAddr);

        listing.clearCodeUnits(startAddr, endAddr, false);
        Disassembler disassembler = Disassembler.getDisassembler(currentProgram, monitor, null);
        for (long seed : seeds) {
            disassembler.disassemble(space.getAddress(seed), set, false);
        }

        Address cur = startAddr;
        int count = 0;
        int maxUnits = 2000;
        while (cur != null && cur.compareTo(endAddr) < 0 && count < maxUnits) {
            CodeUnit cu = listing.getCodeUnitAt(cur);
            if (cu != null) {
                println("DUMP: " + cu.getAddress() + "  len=" + cu.getLength() + "  " + cu);
                cur = cu.getMaxAddress().add(1);
            } else {
                cur = cur.add(1);
            }
            count++;
        }
        println("DUMP: done, " + count + " units/gap-steps walked");
    }
}
