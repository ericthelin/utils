#!/usr/bin/perl -w
# build a program from its archive or source directory
$| = 1;

my $opt_t;

use strict;

my $start;
my $done;
my $TIMEVAL_T;

if ($opt_t) {
    require 'sys/syscall.ph';
    $TIMEVAL_T = "LL";
    $start     = pack( $TIMEVAL_T, () );
    $done      = $start;
    syscall( &SYS_gettimeofday, $start, 0 ) != -1 or die "gettimeofday: $!";
}

my $args = "";
my @DIR;

foreach my $file (@ARGV) {
    if ( -f $file ) {
        my $filetype = `file $file`;

        # print "--------------------------------\n";
        # print "x=$file\n";
        # print "file=$file\n";
        my $type;
        if    ( $filetype =~ /GNU tar archive/ )  { $type = "tar"; }
        elsif ( $filetype =~ /tar archive/ )      { $type = "tar"; }
        elsif ( $filetype =~ /Zip archive data/ ) { $type = "zip"; }
        elsif ( $filetype =~ /gzip compressed/ ) {
            if ( $file =~ /\.tar/i || $filetype =~ /original filename.*\.tar/i ) {
                $type = "tar.gz";
            } else {
                $type = "gz";
            }
        } elsif ( $filetype =~ /bzip2 compressed/ ) {
            if ( $file =~ /\.tar/i || $filetype =~ /original filename.*\.tar/i ) {
                $type = "tar.bz2";
            } else {
                $type = "bz2";
            }
        } elsif ( $file =~ /\.tar$/i ) {
            $type = "tar";
        } elsif ( $file =~ /\.tar.gz$/i ) {
            $type = "tar.gz";
        } elsif ( $file =~ /\.tar.bz2$/i ) {
            $type = "tar.bz2";
        } elsif ( $file =~ /\.bz2/i ) {
            $type = "bz2";
        } elsif ( $file =~ /\.gz$/i ) {
            $type = "gz";
        } elsif ( $file =~ /\.zip$/i ) {
            $type = "zip";
        } else {
            print "unable to find type for '$file', skipping it.\n";
            next;
        }

        # print "type2=$type\n";
        if ( defined($type) ) {
            my $dir;
            if ( $type eq "tar" ) {
                system "tar -xvf $file 2>&1";
                $dir = $file;
                $dir =~ s/\.tar$//i;
            } elsif ( $type eq "bz2" ) {
                system "bunzip2 -d $file 2>&1";
                $dir = $file;
                $dir =~ s/\.bz2$//i;
            } elsif ( $type eq "gz" ) {
                system "gunzip -d $file 2>&1";
            } elsif ( $type eq "tar.gz" ) {
                system "gunzip -cd $file|tar xvf - 2>&1";
                $dir = $file;
                $dir =~ s/\.tar\.(gz|z)$//i;
            } elsif ( $type eq "tar.bz2" ) {
                system "bunzip2 -cd $file|tar xvf - 2>&1";
                $dir = $file;
                $dir =~ s/\.tar\.bz2$//i;
            } elsif ( $type eq "gz" ) {
                system "gunzip -d $file 2>&1";
                $dir = $file;
                $dir =~ s/\.gz$//i;
            } elsif ( $type eq "zip" ) {
                system "unzip $file 2>&1";
                $dir = $file;
                $dir =~ s/\.zip$//i;
            } elsif ( $type eq "rpm" ) {
                system "rpm -Uvh $file 2>&1";

                #$dir=$file;
                #$dir=~s/\.$//i;
            }
            if ($dir) {
                push( @DIR, $dir );
            }
        }
    } else {
        $args .= $file . " ";
    }
}
if ( scalar(@DIR) == 0 ) {
    @DIR = (".");
}
if ( !defined($args) ) {
    $args = "";
}
foreach my $d (@DIR) {
    chdir($d);
    if ( -x "do-conf" ) {
        print "\nCONFIGURE (DO-CONF):\n\n";
        system "./do-conf $args 2>&1";
        if ( $? != 0 ) {
            print "do-conf error: $?\n";
            exit -1;
        }
        if ( -s "config.mak" ) {
            print "\nQMAKE:\n\n";
            system "qmake 2>&1";
            if ( $? != 0 ) {
                print "qmake error: $?\n";
                exit -1;
            }
        }
        if ( -s "Makefile" ) {
            print "\nMAKE:\n\n";
            system "make 2>&1";
            if ( $? != 0 ) {
                print "make error: $?\n";
                exit -1;
            }
            print "\nMAKE INSTALL:\n\n";
            system "make install 2>&1";
            if ( $? != 0 ) {
                print "make install error: $?\n";
                exit -1;
            }
        }
    } elsif ( -s "configure" ) {
        print "\nCONFIGURE:\n\n";
        if ($args) {
            print "\tARGS: $args\n";
        }
        system "./configure $args 2>&1";
        if ( $? != 0 ) {
            print "configure error: $?\n";
            exit -1;
        }
        if ( -s "config.mak" ) {
            print "\nQMAKE:\n\n";
            system "qmake 2>&1";
            if ( $? != 0 ) {
                print "qmake error: $?\n";
                exit -1;
            }
        }
        if ( -s "Makefile" ) {
            print "\nMAKE:\n\n";
            system "make 2>&1";
            if ( $? != 0 ) {
                print "make error: $?\n";
                exit -1;
            }
            print "\nMAKE INSTALL:\n\n";
            system "make install 2>&1";
            if ( $? != 0 ) {
                print "make install error: $?\n";
                exit -1;
            }
        }
    } elsif ( -s "config.m4" ) {
        print "\nPHPIZE:\n\n";
        system "phpize 2>&1";
        if ( $? != 0 ) {
            print "phpize error: $?\n";
            exit -1;
        }
        if ( -s "configure" ) {
            print "\nCONFIGURE:\n\n";
            system "./configure $args 2>&1";
            if ( $? != 0 ) {
                print "configure error: $?\n";
                exit -1;
            }
        } else {
            print "configure not found after phpize: ($?)\n";
            exit -1;
        }
        if ( -s "Makefile" ) {
            print "\nMAKE:\n\n";
            system "make 2>&1";
            if ( $? != 0 ) {
                print "make error: $?\n";
                exit -1;
            }
            print "\nMAKE INSTALL:\n\n";
            system "make install 2>&1";
            if ( $? != 0 ) {
                print "make install error: $?\n";
                exit -1;
            }
        }
    } elsif ( -s "Imakefile" ) {
        print "\nXMKMF:\n\n";
        system "xmkmf 2>&1";
        if ( $? == 0 ) {
            print "\nMAKE:\n\n";
            system "make 2>&1";
        }
        if ( $? == 0 ) {
            print "\nMAKE INSTALL:\n\n";
            system "make install 2>&1";
        }
    } elsif ( -s "Makefile.PL" ) {
        print "\nPERL MAKEFILE.PL:\n\n";
        system "perl Makefile.PL 2>&1";
        if ( $? == 0 ) {
            print "\nMAKE:\n\n";
            system "make 2>&1";
        }
        if ( $? == 0 ) {
            print "\nMAKE TEST:\n\n";
            system "make test 2>&1";
        }
        if ( $? == 0 ) {
            print "\nMAKE INSTALL:\n\n";
            system "make install 2>&1";
        }
    } elsif ( -s "autogen.sh" ) {
        print "\nPERL AUTOGEN.SH:\n\n";
        system "perl autogen.sh 2>&1";
        if ( $? == 0 ) {
            print "\nMAKE:\n\n" . system "make 2>&1";
        }
        if ( $? == 0 ) {
            print "\nMAKE TEST:\n\n";
            system "make test 2>&1";
        }
        if ( $? == 0 ) {
            print "\nMAKE INSTALL:\n\n";
            system "make install 2>&1";
        }
    } elsif ( -s "vmlinux" || ( -s "kernel" && -s "arch" ) ) {
        print "\nMAKE DEP:\n\n";
        system "make dep 2>&1";
        print "\n---/MAKE dep---\n";
        if ( $? == 0 ) {
            print "\nMAKE CLEAN:\n\n";
            system "make clean 2>&1";
            print "\n---/MAKE clean---\n";
        }
        if ( $? == 0 ) {
            print "\nMAKE BZIMAGE:\n\n";
            system "make bzImage 2>&1";
            print "\n---/MAKE bzImage---\n";
        }
        if ( $? == 0 ) {
            print "\nMAKE MODULES:\n\n";
            system "make modules 2>&1";
            print "\n---/MAKE modules---\n";
        }
        if ( $? == 0 ) {
            print "\nMAKE MODULES_INSTALL:\n\n";
            system "make modules_install 2>&1";
            print "\n---/MAKE modules_install---\n";
        }
        if ( $? == 0 ) {
            print "\nMAKE INSTALL:\n\n";
            system "make install 2>&1";
            print "\n---/MAKE install---\n";
        }
    } elsif ( -s "CMakeLists.txt" ) {
        print "\nCMAKE:\n\n";
        system "cmake . $args 2>&1";
        if ( $? != 0 ) {
            print "cmake error: $?\n";
            exit -1;
        }
        print "\nMAKE:\n\n";
        system "make 2>&1";
        if ( $? != 0 ) {
            print "make error: $?\n";
            exit -1;
        }
        print "\nMAKE INSTALL:\n\n";
        system "make install 2>&1";
        if ( $? != 0 ) {
            print "make install error: $?\n";
            exit -1;
        }
    } elsif ( -s "Makefile" || -s "makefile" ) {
        print "\nMAKE:\n\n";
        system "make $args 2>&1";
        if ( $? != 0 ) {
            print "make error: $?\n";
            exit -1;
        }
        print "\nMAKE INSTALL:\n\n";
        system "make install $args 2>&1";
        if ( $? != 0 ) {
            print "make install error: $?\n";
            exit -1;
        }
    } else {
        print "\nUNKNOWN make type\n\n";
    }
    chdir("..");
}
if ($opt_t) {
    syscall( &SYS_gettimeofday, $done, 0 ) != -1 or die "gettimeofday: $!";
    my @start = unpack( $TIMEVAL_T, $start );
    my @done  = unpack( $TIMEVAL_T, $done );

    # fix microseconds
    for ( $done[1], $start[1] ) { $_ /= 1_000_000 }
    my $elapsed = ( $done[0] + $done[1] ) - ( $start[0] + $start[1] );
    my ( $user, $system, $cuser, $csystem ) = times;
    printf( "\nuser: %.4fs\tsystem: %.4fs\telapsed: %.4fs\n\n", $cuser + $user, $csystem + $system, $elapsed );
}

# print "user: $user\n";
# print "system: $system\n";
# print "cuser: $cuser\n";
# print "csystem: $csystem\n";
# $delta_time = sprintf "%.4f",$elapsed ;
# print "elapsed: $delta_time\n";
